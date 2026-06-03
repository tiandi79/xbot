"""
Detect tweets the logged-in user already replied to (manual or bot).
"""

import re
import time
from typing import Optional, Set

from playwright.sync_api import Page

from utils.logger import has_published_for_post, mark_post_as_replied

STATUS_ID_RE = re.compile(r"/status/(\d+)")


def extract_status_id(href: str) -> Optional[str]:
    if not href:
        return None
    m = STATUS_ID_RE.search(href)
    return m.group(1) if m else None


def get_logged_in_username(page: Page) -> Optional[str]:
    """Read @handle from nav profile link."""
    selectors = [
        'a[data-testid="AppTabBar_Profile_Link"]',
        'a[data-testid="SideNav_AccountSwitcher_Button"]',
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel)
            if loc.count() == 0:
                continue
            href = (loc.first.get_attribute("href") or "").strip()
            if not href or href == "/home":
                continue
            parts = [p for p in href.split("/") if p]
            if parts and parts[0] not in ("home", "i", "explore", "notifications", "messages"):
                return parts[0].lstrip("@")
        except Exception:
            continue
    return None


def _article_own_status_id(article) -> Optional[str]:
    try:
        link = article.locator('a[href*="/status/"]').first
        return extract_status_id(link.get_attribute("href") or "")
    except Exception:
        return None


def _article_author_username(article) -> Optional[str]:
    try:
        link = article.locator('[data-testid="User-Name"] a[role="link"]').first
        href = (link.get_attribute("href") or "").strip()
        parts = [p for p in href.split("/") if p]
        if parts:
            return parts[0].lstrip("@").lower()
    except Exception:
        pass
    return None


def user_replied_on_status_page(page: Page, root_tweet_id: str, my_username: str) -> bool:
    """True if my_username already has a reply in this status thread."""
    if not my_username or not root_tweet_id:
        return False
    me = my_username.lower()
    try:
        articles = page.locator('article[data-testid="tweet"]')
        count = articles.count()
        for i in range(count):
            if i == 0:
                continue
            art = articles.nth(i)
            author = _article_author_username(art)
            if author == me:
                return True
    except Exception:
        pass
    return False


def _parent_ids_from_reply_article(article) -> Set[str]:
    """Best-effort: parent tweet id(s) a reply card refers to."""
    parent_ids: Set[str] = set()
    own_id = _article_own_status_id(article)

    try:
        ctx = article.locator('[data-testid="socialContext"]')
        if ctx.count() > 0:
            for link in ctx.locator('a[href*="/status/"]').all():
                tid = extract_status_id(link.get_attribute("href") or "")
                if tid and tid != own_id:
                    parent_ids.add(tid)
    except Exception:
        pass

    try:
        for link in article.locator('a[href*="/status/"]').all():
            tid = extract_status_id(link.get_attribute("href") or "")
            if tid and tid != own_id:
                parent_ids.add(tid)
    except Exception:
        pass

    return parent_ids


def sync_replied_posts_from_profile(
    page: Page,
    username: str,
    max_scroll_rounds: int = 12,
    pause_sec: float = 1.2,
) -> int:
    """
    Visit /{username}/with_replies and record parent tweet ids into published_log.
    Replies are newest-first; stop scrolling once we hit posts already in the log.
    Returns count of newly recorded posts.
    """
    if not username:
        return 0

    url = f"https://x.com/{username}/with_replies"
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        time.sleep(2.0)
    except Exception as e:
        print(f"[xbot] Warning: cannot open with_replies page: {e}")
        return 0

    seen_reply_ids: Set[str] = set()
    new_count = 0
    stop_scrolling = False

    for round_idx in range(max_scroll_rounds):
        if stop_scrolling:
            break

        articles = page.locator('article[data-testid="tweet"]')
        try:
            n = articles.count()
        except Exception:
            break

        batch: list[tuple[int, object]] = []
        for i in range(n):
            try:
                art = articles.nth(i)
                own_id = _article_own_status_id(art)
                if not own_id or own_id in seen_reply_ids:
                    continue
                seen_reply_ids.add(own_id)
                batch.append((i, art))
            except Exception:
                continue

        # Top of page = newer replies; stop when we reach already-synced history.
        for i, art in sorted(batch, key=lambda x: x[0]):
            parent_ids = _parent_ids_from_reply_article(art)
            if not parent_ids:
                continue

            unknown = [p for p in parent_ids if p and not has_published_for_post(p)]
            if unknown:
                for parent_id in unknown:
                    if mark_post_as_replied(
                        parent_id,
                        tweet_url=f"https://x.com/i/status/{parent_id}",
                        source="sync_replies",
                    ):
                        new_count += 1
            else:
                print(
                    f"[xbot] 回复同步已追上已有记录（原帖 {', '.join(sorted(parent_ids))}），"
                    "不再向下滚动"
                )
                stop_scrolling = True
                break

        if stop_scrolling:
            break

        if round_idx + 1 >= max_scroll_rounds:
            break

        page.evaluate(
            "window.scrollBy(0, Math.floor(window.innerHeight * (0.6 + Math.random() * 0.5)))"
        )
        time.sleep(pause_sec)

    return new_count


def _find_visible_reply_button(page: Page):
    """Return reply button locator if already on screen, else None."""
    reply_button_selectors = [
        '[data-testid="reply"]',
        'div[aria-label*="Reply"]',
        'button[aria-label*="回复"]',
    ]
    for selector in reply_button_selectors:
        loc = page.locator(selector)
        if loc.count() == 0:
            continue
        btn = loc.first
        try:
            if btn.is_visible():
                return btn
        except Exception:
            continue
    return None


def ensure_reply_button_visible(page: Page):
    """
    Find reply button; scroll only when it is not already visible.
    """
    btn = _find_visible_reply_button(page)
    if btn:
        return btn

    articles = page.locator('article[data-testid="tweet"]')
    try:
        if articles.count() > 0:
            articles.first.scroll_into_view_if_needed(timeout=5000)
            time.sleep(0.35)
    except Exception:
        pass

    btn = _find_visible_reply_button(page)
    if btn:
        return btn

    for _ in range(6):
        try:
            page.evaluate("window.scrollBy(0, 160)")
            time.sleep(0.35)
        except Exception:
            break
        btn = _find_visible_reply_button(page)
        if btn:
            return btn

    for selector in (
        '[data-testid="reply"]',
        'div[aria-label*="Reply"]',
        'button[aria-label*="回复"]',
    ):
        loc = page.locator(selector)
        if loc.count() == 0:
            continue
        btn = loc.first
        try:
            btn.scroll_into_view_if_needed(timeout=3000)
            time.sleep(0.3)
            if btn.is_visible():
                return btn
        except Exception:
            continue

    return None
