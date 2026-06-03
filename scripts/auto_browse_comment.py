#!/usr/bin/env python3
"""
自动打开 Chrome 浏览 X 热门中文帖，对浏览量超过阈值的帖子发表评论。
已评论过的帖子会跳过（记录在 data/published_log.json）。
"""

import argparse
import os
import random
import re
import sys
import time
from pathlib import Path

# Windows 终端 UTF-8 输出
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from utils.comment_generator import generate_comments
from utils.comment_marker import apply_auto_marker
from utils.logger import has_published_for_post, log_published_comment
from utils.reply_guard import (
    ensure_reply_button_visible,
    get_logged_in_username,
    sync_replied_posts_from_profile,
    user_replied_on_status_page,
)
from utils.x_browser import (
    connect_or_launch,
    ensure_x_ready,
    list_cdp_tabs,
    wait_for_cdp,
)
from utils.x_publisher import publish_comment, DEFAULT_COOKIES_PATH
from utils.x_scraper import (
    DEFAULT_SCROLL_MAX,
    DEFAULT_SCROLL_MIN,
    DEFAULT_SCROLL_PAUSE_MAX,
    DEFAULT_SCROLL_PAUSE_MIN,
    is_promoted_ad,
    scrape_timeline_posts,
)


def _tweet_id_from_url(url: str) -> str:
    m = re.search(r"/status/(\d+)", url or "")
    return m.group(1) if m else ""


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)).strip())
    except (TypeError, ValueError):
        return default


def _comment_limit_reached(commented: int, max_comments: int) -> bool:
    return max_comments > 0 and commented >= max_comments


def _sleep_between_comments(interval_sec: float, max_comments: int) -> None:
    """Wait before next comment. Skipped when max_comments is 1 (single-shot run)."""
    if max_comments == 1:
        return
    lo = _env_float("COMMENT_INTERVAL_JITTER_MIN", 0.5)
    hi = _env_float("COMMENT_INTERVAL_JITTER_MAX", 1.5)
    if lo > hi:
        lo, hi = hi, lo
    delay = interval_sec * random.uniform(lo, hi)
    print(f"[xbot] 间隔 {delay:.0f}s 后发下一条（基准 {interval_sec:.0f}s × {lo}-{hi} 随机）…")
    time.sleep(delay)


def publish_on_page(page, tweet_url: str, comment_text: str, my_username: str = "") -> dict:
    """Publish reply using an already-open browser page."""
    import random
    import time
    from playwright.sync_api import TimeoutError as PlaywrightTimeout

    try:
        page.goto(tweet_url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(random.uniform(1.5, 3.0))

        root_id = _tweet_id_from_url(tweet_url)
        if my_username and user_replied_on_status_page(page, root_id, my_username):
            mark_post_as_replied(
                root_id,
                tweet_url=tweet_url,
                source="detected_on_page",
            )
            return {
                "success": False,
                "message": "跳过（页面上已有你的回复）",
                "error": "Already replied",
            }

        main_tweet = page.locator('article[data-testid="tweet"]')
        try:
            if main_tweet.count() > 0 and is_promoted_ad(main_tweet.first):
                return {"success": False, "message": "跳过广告帖", "error": "Promoted tweet"}
        except Exception:
            pass

        reply_btn = ensure_reply_button_visible(page)
        reply_clicked = False
        if reply_btn:
            try:
                reply_btn.click()
                reply_clicked = True
            except Exception:
                reply_clicked = False

        if not reply_clicked:
            return {"success": False, "message": "无法找到回复按钮", "error": "Reply button not found"}

        time.sleep(random.uniform(1.0, 2.0))

        textarea_selectors = [
            '[data-testid="tweetTextarea_0"]',
            'div[role="textbox"][aria-label*="回复"]',
            'div[contenteditable="true"]',
        ]
        reply_box = None
        for selector in textarea_selectors:
            try:
                box = page.locator(selector).first
                if box.is_visible():
                    reply_box = box
                    break
            except Exception:
                continue

        if not reply_box:
            return {"success": False, "message": "无法找到回复输入框", "error": "Reply box not found"}

        reply_box.click()
        time.sleep(0.5)
        page.keyboard.type(comment_text, delay=80)
        time.sleep(random.uniform(1.2, 2.5))

        post_button_selectors = [
            '[data-testid="tweetButton"]',
            'div[role="button"][data-testid="tweetButtonInline"]',
            'button[aria-label*="发帖"]',
        ]
        posted = False
        for selector in post_button_selectors:
            try:
                post_btn = page.locator(selector).first
                if post_btn.is_visible() and post_btn.is_enabled():
                    post_btn.click()
                    posted = True
                    break
            except Exception:
                continue

        if not posted:
            return {"success": False, "message": "无法找到发布按钮", "error": "Post button not found"}

        time.sleep(random.uniform(2.5, 4.5))
        return {"success": True, "message": "评论发布成功", "error": None}

    except PlaywrightTimeout as e:
        return {"success": False, "message": "页面加载超时", "error": str(e)}
    except Exception as e:
        return {"success": False, "message": "发布过程中发生错误", "error": str(e)}


def main():
    default_max_comments = _env_int("MAX_COMMENTS", 1)
    default_interval = _env_float("COMMENT_INTERVAL_SEC", 60)
    default_min_views = _env_int("MIN_VIEWS", 10000)

    parser = argparse.ArgumentParser(description="X 自动浏览并评论（中文帖、高浏览量）")
    parser.add_argument(
        "--min-views",
        type=int,
        default=default_min_views,
        help="最低浏览量（默认 .env MIN_VIEWS=10000）",
    )
    parser.add_argument(
        "--max-comments",
        type=int,
        default=default_max_comments,
        help="本次最多评论条数（默认 .env MAX_COMMENTS=1；0=不限，一直发）",
    )
    parser.add_argument(
        "--comment-interval",
        type=float,
        default=default_interval,
        help="每条评论间隔秒数（默认 .env COMMENT_INTERVAL_SEC=60；仅 max-comments≠1 时生效）",
    )
    parser.add_argument("--scroll-rounds", type=int, default=10, help="滚动加载轮数（默认 10）")
    parser.add_argument(
        "--scroll-min",
        type=int,
        default=DEFAULT_SCROLL_MIN,
        help=f"每次滚动最小像素（默认 {DEFAULT_SCROLL_MIN}，可在 .env 设 SCROLL_MIN）",
    )
    parser.add_argument(
        "--scroll-max",
        type=int,
        default=DEFAULT_SCROLL_MAX,
        help=f"每次滚动最大像素（默认 {DEFAULT_SCROLL_MAX}，可在 .env 设 SCROLL_MAX）",
    )
    parser.add_argument(
        "--scroll-pause-min",
        type=float,
        default=DEFAULT_SCROLL_PAUSE_MIN,
        help=f"滚动后最短停顿秒数（默认 {DEFAULT_SCROLL_PAUSE_MIN}）",
    )
    parser.add_argument(
        "--scroll-pause-max",
        type=float,
        default=DEFAULT_SCROLL_PAUSE_MAX,
        help=f"滚动后最长停顿秒数（默认 {DEFAULT_SCROLL_PAUSE_MAX}）",
    )
    parser.add_argument("--dry-run", action="store_true", help="只浏览不发表评论")
    parser.add_argument(
        "--no-marker",
        action="store_true",
        help="不追加自动评论末尾标记",
    )
    parser.add_argument(
        "--no-sync-replies",
        action="store_true",
        help="不从你的「回复」页同步已手动回复的帖子",
    )
    parser.add_argument(
        "--new-browser",
        action="store_true",
        help="启动新 Chrome（默认连接已打开的 Chrome 并复用 X 页签）",
    )
    args = parser.parse_args()

    if args.scroll_min > args.scroll_max:
        args.scroll_min, args.scroll_max = args.scroll_max, args.scroll_min
    if args.scroll_pause_min > args.scroll_pause_max:
        args.scroll_pause_min, args.scroll_pause_max = args.scroll_pause_max, args.scroll_pause_min

    cookies_path = os.getenv("COOKIES_PATH", DEFAULT_COOKIES_PATH)
    cdp_only = not args.new_browser
    unlimited = args.max_comments == 0
    limit_label = "不限（一直发）" if unlimited else str(args.max_comments)
    print(f"[xbot] cookies: {cookies_path}")
    print(f"[xbot] 条件: 中文帖 | 非广告 | 浏览量 >= {args.min_views:,} | 评论条数 {limit_label}")
    if args.max_comments != 1:
        print(
            f"[xbot] 评论间隔: 基准 {args.comment_interval:.0f}s，"
            f"实际 {_env_float('COMMENT_INTERVAL_JITTER_MIN', 0.5)}-"
            f"{_env_float('COMMENT_INTERVAL_JITTER_MAX', 1.5)} 倍随机"
        )
    else:
        print("[xbot] 评论间隔: 仅发 1 条，间隔不生效")
    print(
        f"[xbot] 滚动: {args.scroll_rounds} 轮 | "
        f"距离 {args.scroll_min}-{args.scroll_max}px 随机 | "
        f"停顿 {args.scroll_pause_min}-{args.scroll_pause_max}s 随机"
    )
    if cdp_only:
        print("[xbot] 模式: 连接已打开的 Chrome（复用 X 页签，不会启动新浏览器）")
        if not wait_for_cdp(timeout_sec=5):
            print("[xbot] CDP 未就绪。请先运行 scripts\\start_chrome_cdp.bat")
            print(f"[xbot] 当前页签: {list_cdp_tabs() or ['(无)']}")
            sys.exit(1)
        print(f"[xbot] CDP 已连接，检测到页签: {list_cdp_tabs()}")

    try:
        pw, browser, context, page, should_close = connect_or_launch(
            cookies_path=cookies_path,
            headless=False,
            cdp_only=cdp_only,
        )
    except RuntimeError as e:
        print(f"[xbot] 错误: {e}")
        sys.exit(1)

    using_existing_tab = cdp_only and not should_close
    has_x_tab = "x.com" in (page.url or "").lower() or "twitter.com" in (page.url or "").lower()
    if using_existing_tab:
        print(f"[xbot] 已连接 Chrome，复用页签: {page.url}")

    commented = 0
    my_username = ""
    try:
        ensure_x_ready(page, reuse_tab=using_existing_tab and has_x_tab)
        my_username = get_logged_in_username(page) or os.getenv("X_USERNAME", "").lstrip("@")
        if my_username:
            print(f"[xbot] 当前账号: @{my_username}")
        if my_username and not args.no_sync_replies and not args.dry_run:
            print("[xbot] 增量同步手动回复（仅补新记录，遇到已记录即停止滚动）…")
            synced = sync_replied_posts_from_profile(page, my_username)
            print(f"[xbot] 同步完成，本次新增 {synced} 条")
            ensure_x_ready(page, reuse_tab=True)

        if using_existing_tab and has_x_tab:
            print("[xbot] 在当前 X 页签浏览时间线 …")
        elif using_existing_tab:
            print("[xbot] 请在 Chrome 中打开 x.com/home 后再运行")
            sys.exit(1)
        else:
            print("[xbot] 已打开 X 首页，开始浏览时间线 …")

        if not using_existing_tab:
            # 也可切到「探索」增加热门曝光
            try:
                explore = page.locator('a[href="/explore"]').first
                if explore.is_visible(timeout=2000):
                    explore.click()
                    time.sleep(2)
                    page.goto("https://x.com/home", wait_until="domcontentloaded")
                    time.sleep(2)
            except Exception:
                pass

        scrape_batch = _env_int("COMMENT_SCRAPE_BATCH", 30) if unlimited else max(args.max_comments * 3, 3)
        round_no = 0

        while True:
            if _comment_limit_reached(commented, args.max_comments):
                break
            round_no += 1
            if round_no > 1:
                print(f"\n[xbot] 第 {round_no} 轮浏览时间线 …")
                ensure_x_ready(page, reuse_tab=True)

            posts = scrape_timeline_posts(
                page,
                min_views=args.min_views,
                chinese_only=True,
                exclude_ads=True,
                max_posts=scrape_batch,
                scroll_rounds=args.scroll_rounds,
                scroll_min=args.scroll_min,
                scroll_max=args.scroll_max,
                scroll_pause_min=args.scroll_pause_min,
                scroll_pause_max=args.scroll_pause_max,
            )

            print(f"[xbot] 找到 {len(posts)} 条符合条件的中文高浏览量帖子")
            if not posts:
                if commented == 0:
                    print("[提示] 未找到可评论帖子，可稍后重试或降低 --min-views。")
                break

            round_commented = 0
            for i, post in enumerate(posts, 1):
                if _comment_limit_reached(commented, args.max_comments):
                    break

                if has_published_for_post(post.tweet_id):
                    print(f"  [{i}] 跳过（已评论过） @{post.author_username} | {post.views:,} 浏览")
                    continue

                print(f"\n  [{i}] @{post.author_username} | {post.views:,} 浏览")
                print(f"      {post.text[:80]}{'…' if len(post.text) > 80 else ''}")

                if args.dry_run:
                    print("      [dry-run] 不发表评论")
                    continue

                try:
                    comments = generate_comments(post.text, post.author_username or "user", num_comments=1)
                    comment = comments[0]
                except Exception as e:
                    print(f"      评论生成失败: {e}")
                    continue

                marker = ""
                marker_pos = -1
                if not args.no_marker:
                    comment, marker, marker_pos = apply_auto_marker(comment, post.tweet_id)

                print(f"      评论: {comment[:80]}{'…' if len(comment) > 80 else ''}")
                if marker:
                    print(f"      [auto marker] space U+{ord(marker):04X} at index {marker_pos}")

                result = publish_on_page(page, post.url, comment, my_username=my_username)
                if not result["success"]:
                    print(f"      页面发布失败: {result.get('message')}")
                    if result.get("error") in ("Promoted tweet", "Already replied"):
                        print("      跳过此帖，尝试下一条 …")
                        continue
                    if should_close:
                        print("      尝试独立会话 …")
                        result = publish_comment(post.url, comment, cookies_path=cookies_path)
                    else:
                        print("      跳过此帖，尝试下一条 …")
                        continue

                if result["success"]:
                    log_published_comment(
                        post.tweet_id,
                        post.url,
                        comment,
                        post.author_username,
                        marker=marker,
                        marker_pos=marker_pos,
                    )
                    commented += 1
                    round_commented += 1
                    done_label = limit_label if not unlimited else str(commented)
                    print(f"      [OK] 发布成功 ({commented}/{done_label})")
                    if not _comment_limit_reached(commented, args.max_comments):
                        _sleep_between_comments(args.comment_interval, args.max_comments)
                else:
                    print(f"      [FAIL] 发布失败: {result.get('message')} | {result.get('error', '')}")

            if not unlimited or round_commented == 0:
                break

        print(f"\n[xbot] 完成。本次新评论 {commented} 条。")
        if commented == 0 and not args.dry_run:
            print("[提示] 时间线可能未展示浏览量，或当前没有 >=1万 浏览的中文帖。可稍后重试或降低 --min-views。")

    finally:
        if should_close:
            browser.close()
        pw.stop()


if __name__ == "__main__":
    main()
