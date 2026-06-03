"""
Scrape tweets from X timeline with view counts and Chinese filtering.
"""

import os
import random
import re
import time
from dataclasses import dataclass
from typing import List, Optional, Set

from playwright.sync_api import Page

# 默认滚动参数（可通过 .env 或命令行覆盖）
DEFAULT_SCROLL_MIN = int(os.getenv("SCROLL_MIN", "800"))
DEFAULT_SCROLL_MAX = int(os.getenv("SCROLL_MAX", "2800"))
DEFAULT_SCROLL_PAUSE_MIN = float(os.getenv("SCROLL_PAUSE_MIN", "1.2"))
DEFAULT_SCROLL_PAUSE_MAX = float(os.getenv("SCROLL_PAUSE_MAX", "3.5"))

CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
AD_LABELS = ("promoted", "推广", "广告", "赞助", "sponsored", "ad")
VIEW_PATTERNS = [
    re.compile(r"([\d,.]+)\s*万\s*(?:次)?(?:观看|浏览|查看)?", re.I),
    re.compile(r"([\d,.]+)\s*[Kk]\s*(?:views?)?"),
    re.compile(r"([\d,.]+)\s*(?:views?|次观看|次浏览)", re.I),
    re.compile(r"([\d,.]+)\s*(?:Views?|views?)"),
]


@dataclass
class ScrapedPost:
    tweet_id: str
    url: str
    author_username: str
    text: str
    views: int


def is_chinese_post(text: str, min_ratio: float = 0.15) -> bool:
    """True if text contains enough Chinese characters."""
    if not text or not text.strip():
        return False
    cjk = len(CJK_RE.findall(text))
    # ignore URLs and mentions for ratio
    cleaned = re.sub(r"https?://\S+|@\w+", "", text)
    if not cleaned.strip():
        return cjk >= 8
    letters = len(re.findall(r"\w", cleaned, re.UNICODE))
    if letters == 0:
        return cjk >= 4
    return (cjk / max(letters, 1)) >= min_ratio or cjk >= 12


def parse_view_count(raw: str) -> Optional[int]:
    if not raw:
        return None
    s = raw.strip().replace(",", "").replace(" ", "")
    for pat in VIEW_PATTERNS:
        m = pat.search(s)
        if not m:
            continue
        num_str = m.group(1).replace(",", "")
        try:
            val = float(num_str)
        except ValueError:
            continue
        if "万" in s or "万" in raw:
            return int(val * 10000)
        if re.search(r"[Kk]", s) or re.search(r"[Kk]", raw):
            return int(val * 1000)
        return int(val)
    # plain number
    digits = re.sub(r"[^\d.]", "", s)
    if digits:
        try:
            return int(float(digits))
        except ValueError:
            pass
    return None


def is_promoted_ad(article) -> bool:
    """Detect X promoted / sponsored tweets in a timeline article."""
    try:
        if article.locator('[data-testid="placementTracking"]').count() > 0:
            return True
    except Exception:
        pass

    try:
        ctx = article.locator('[data-testid="socialContext"]')
        if ctx.count() > 0:
            text = (ctx.first.inner_text(timeout=500) or "").strip().lower()
            if text and any(label in text for label in AD_LABELS):
                return True
    except Exception:
        pass

    try:
        for span in article.locator("span").all()[:40]:
            text = (span.inner_text(timeout=300) or "").strip().lower()
            if text in AD_LABELS or text in ("promoted", "推广", "广告", "赞助"):
                return True
    except Exception:
        pass

    try:
        label = (article.get_attribute("aria-label") or "").lower()
        if label and any(k in label for k in AD_LABELS):
            return True
    except Exception:
        pass

    try:
        snippet = (article.inner_text(timeout=800) or "").lower()
        first_line = snippet.split("\n", 1)[0].strip()
        if first_line in AD_LABELS or first_line in ("promoted", "推广", "广告", "赞助"):
            return True
    except Exception:
        pass

    return False


def _extract_views_from_article(article) -> Optional[int]:
    candidates = []
    for sel in [
        'a[href*="/analytics"]',
        '[data-testid="app-text-transition-container"]',
        'span',
        'div[role="group"] span',
    ]:
        try:
            els = article.locator(sel).all()
            for el in els[:20]:
                txt = el.inner_text(timeout=500) if el else ""
                if txt and ("view" in txt.lower() or "观看" in txt or "浏览" in txt or "万" in txt or re.search(r"\d+[Kk]", txt)):
                    candidates.append(txt)
        except Exception:
            continue

    for txt in candidates:
        v = parse_view_count(txt)
        if v is not None:
            return v
    return None


def _extract_tweet_id(href: str) -> Optional[str]:
    m = re.search(r"/status/(\d+)", href or "")
    return m.group(1) if m else None


def human_scroll_page(
    page: Page,
    *,
    scroll_min: int = DEFAULT_SCROLL_MIN,
    scroll_max: int = DEFAULT_SCROLL_MAX,
    pause_min: float = DEFAULT_SCROLL_PAUSE_MIN,
    pause_max: float = DEFAULT_SCROLL_PAUSE_MAX,
) -> int:
    """Scroll down with random distance and pause to mimic human browsing."""
    scroll_min, scroll_max = min(scroll_min, scroll_max), max(scroll_min, scroll_max)
    delta_y = random.randint(scroll_min, scroll_max)
    # 约 15% 概率小幅回滚，更像真人浏览
    if random.random() < 0.15:
        delta_y = -random.randint(120, min(400, scroll_min))
    page.mouse.wheel(0, delta_y)
    time.sleep(random.uniform(pause_min, pause_max))
    return delta_y


def scrape_timeline_posts(
    page: Page,
    *,
    min_views: int = 10000,
    chinese_only: bool = True,
    exclude_ads: bool = True,
    max_posts: int = 15,
    scroll_rounds: int = 8,
    scroll_min: int = DEFAULT_SCROLL_MIN,
    scroll_max: int = DEFAULT_SCROLL_MAX,
    scroll_pause_min: float = DEFAULT_SCROLL_PAUSE_MIN,
    scroll_pause_max: float = DEFAULT_SCROLL_PAUSE_MAX,
    seen_ids: Optional[Set[str]] = None,
) -> List[ScrapedPost]:
    """Scroll home/explore feed and collect qualifying posts."""
    seen_ids = seen_ids or set()
    results: List[ScrapedPost] = []
    collected_ids: Set[str] = set()

    for _ in range(scroll_rounds):
        articles = page.locator('article[data-testid="tweet"]').all()
        for article in articles:
            try:
                link = article.locator('a[href*="/status/"]').first
                href = link.get_attribute("href") or ""
                tweet_id = _extract_tweet_id(href)
                if not tweet_id or tweet_id in seen_ids or tweet_id in collected_ids:
                    continue

                if exclude_ads and is_promoted_ad(article):
                    continue

                text_el = article.locator('[data-testid="tweetText"]').first
                text = ""
                try:
                    text = text_el.inner_text(timeout=800)
                except Exception:
                    text = article.inner_text(timeout=1000)[:500]

                if chinese_only and not is_chinese_post(text):
                    continue

                views = _extract_views_from_article(article)
                if views is None or views < min_views:
                    continue

                author = ""
                try:
                    author_link = article.locator('a[href^="/"][role="link"]').first
                    ah = author_link.get_attribute("href") or ""
                    author = ah.strip("/").split("/")[0] if ah else ""
                except Exception:
                    pass

                url = f"https://x.com/i/status/{tweet_id}" if not href.startswith("http") else (
                    href if href.startswith("http") else f"https://x.com{href}"
                )

                post = ScrapedPost(
                    tweet_id=tweet_id,
                    url=url,
                    author_username=author,
                    text=text.strip(),
                    views=views,
                )
                results.append(post)
                collected_ids.add(tweet_id)
                if len(results) >= max_posts:
                    return results
            except Exception:
                continue

        human_scroll_page(
            page,
            scroll_min=scroll_min,
            scroll_max=scroll_max,
            pause_min=scroll_pause_min,
            pause_max=scroll_pause_max,
        )

    return results
