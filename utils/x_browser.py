"""
Chrome browser helpers for X automation.
Supports CDP attach to running Chrome or launch with cookies.
"""

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Optional, Tuple

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

from utils.x_publisher import load_cookies, DEFAULT_COOKIES_PATH

CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]
CDP_URL = os.getenv("CHROME_CDP_URL", "http://127.0.0.1:9222")
BROWSER_PROXY = (
    os.getenv("BROWSER_PROXY")
    or os.getenv("CHROME_PROXY")
    or os.getenv("HTTPS_PROXY")
    or os.getenv("ALL_PROXY")
)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def find_chrome_exe() -> Optional[str]:
    for path in CHROME_PATHS:
        if path and os.path.isfile(path):
            return path
    return None


def is_cdp_available(cdp_url: str = CDP_URL) -> bool:
    try:
        import urllib.request

        urllib.request.urlopen(cdp_url + "/json/version", timeout=3)
        return True
    except Exception:
        return False


def wait_for_cdp(timeout_sec: float = 30, interval: float = 1.0, cdp_url: str = CDP_URL) -> bool:
    """Wait until Chrome remote debugging port responds."""
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if is_cdp_available(cdp_url):
            return True
        time.sleep(interval)
    return False


def list_cdp_tabs(cdp_url: str = CDP_URL) -> list[str]:
    try:
        import json
        import urllib.request

        raw = urllib.request.urlopen(cdp_url + "/json/list", timeout=3).read()
        tabs = json.loads(raw)
        return [
            t.get("url", "")
            for t in tabs
            if t.get("type") == "page" and t.get("url")
        ]
    except Exception:
        return []


def find_x_page(browser: Browser) -> Optional[Page]:
    """Find an already-open X / Twitter tab across all contexts."""
    for context in browser.contexts:
        for page in context.pages:
            url = (page.url or "").lower()
            if "x.com" in url or "twitter.com" in url:
                return page

    # Playwright 有时拿不到全部页签，用 CDP 列表再匹配一次
    for tab_url in list_cdp_tabs():
        lower = tab_url.lower()
        if "x.com" not in lower and "twitter.com" not in lower:
            continue
        for context in browser.contexts:
            for page in context.pages:
                if page.url == tab_url:
                    return page
    return None


def launch_chrome_with_debugging(port: int = 9222) -> Optional[subprocess.Popen]:
    """Launch a separate Chrome instance with remote debugging (uses temp profile)."""
    chrome = find_chrome_exe()
    if not chrome:
        return None

    profile_dir = Path(os.getenv("TEMP", ".")) / "xbot_chrome_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)

    args = [
        chrome,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--start-minimized",
        "https://x.com",
    ]
    proxy = BROWSER_PROXY
    if proxy:
        args.append(f"--proxy-server={proxy}")
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def connect_existing_chrome(
    cdp_url: str = CDP_URL,
    require_x_tab: bool = True,
) -> Tuple[Playwright, Browser, BrowserContext, Page]:
    """
    Attach to running Chrome via CDP and reuse an open X tab when possible.
    """
    if not is_cdp_available(cdp_url):
        raise RuntimeError(
            "无法连接已打开的 Chrome。请先运行 scripts\\start_chrome_cdp.bat"
        )

    pw = sync_playwright().start()
    browser = pw.chromium.connect_over_cdp(cdp_url)
    page = find_x_page(browser)

    if page:
        context = page.context
        return pw, browser, context, page

    if require_x_tab:
        pw.stop()
        tabs = list_cdp_tabs(cdp_url)
        raise RuntimeError(
            "已连接 Chrome，但没有找到 x.com 页签。\n"
            f"当前页签: {tabs or ['(无)']}"
        )

    context = browser.contexts[0] if browser.contexts else browser.new_context()
    page = context.pages[0] if context.pages else context.new_page()
    return pw, browser, context, page


def inject_x_cookies(context: BrowserContext, cookies_path: str = DEFAULT_COOKIES_PATH) -> None:
    """Inject X cookies into CDP browser context (for login when profile session unavailable)."""
    try:
        context.add_cookies(load_cookies(cookies_path))
    except Exception as e:
        print(f"[xbot] Warning: could not inject cookies: {e}")


def connect_or_launch(
    cookies_path: str = DEFAULT_COOKIES_PATH,
    headless: bool = False,
    cdp_only: bool = False,
) -> Tuple[Playwright, Browser, BrowserContext, Page, bool]:
    """
    Returns (playwright, browser, context, page, should_close_browser).
    Prefers CDP attach; falls back to Playwright Chrome + cookies.
    """
    pw = sync_playwright().start()
    should_close = True

    if cdp_only and not is_cdp_available():
        pw.stop()
        tabs_hint = ", ".join(list_cdp_tabs()[:5]) or "(无)"
        raise RuntimeError(
            "无法连接 Chrome CDP（端口 9222）。\n"
            "请先运行 scripts\\start_chrome_cdp.bat，等待 CDP 就绪并打开 x.com 页签后再执行本脚本。\n"
            f"当前检测到的页签: {tabs_hint}"
        )

    if is_cdp_available():
        browser = pw.chromium.connect_over_cdp(CDP_URL)
        should_close = False
        page = find_x_page(browser)
        context = page.context if page else (browser.contexts[0] if browser.contexts else browser.new_context())
        inject_x_cookies(context, cookies_path)
        if not page:
            if context.pages:
                page = context.pages[0]
            else:
                page = context.new_page()
        try:
            target = "https://x.com/home"
            if "x.com" not in (page.url or "").lower() or "login" in (page.url or "").lower():
                page.goto(target, wait_until="domcontentloaded", timeout=45000)
            else:
                page.reload(wait_until="domcontentloaded", timeout=45000)
            time.sleep(2.5)
        except Exception as e:
            print(f"[xbot] Warning: X page load issue: {e}")
        return pw, browser, context, page, should_close

    if cdp_only:
        pw.stop()
        raise RuntimeError("CDP 模式失败：无法连接 Chrome，也不会启动新浏览器。")

    launch_kwargs = {"channel": "chrome", "headless": headless}
    if BROWSER_PROXY:
        launch_kwargs["proxy"] = {"server": BROWSER_PROXY}

    browser = pw.chromium.launch(**launch_kwargs)
    context_kwargs = {"user_agent": USER_AGENT}
    if BROWSER_PROXY:
        context_kwargs["proxy"] = {"server": BROWSER_PROXY}
    context = browser.new_context(**context_kwargs)
    context.add_cookies(load_cookies(cookies_path))
    page = context.new_page()
    return pw, browser, context, page, should_close


def ensure_x_ready(page: Page, timeout_ms: int = 45000, reuse_tab: bool = False) -> None:
    """Ensure page is on logged-in X timeline."""
    url = (page.url or "").lower()
    on_x = "x.com" in url or "twitter.com" in url
    if reuse_tab and on_x and "login" not in url and "/home" in url:
        time.sleep(1.0)
        return
    target = "https://x.com/home"
    if not on_x or url.rstrip("/").endswith("x.com") or "login" in url:
        page.goto(target, wait_until="domcontentloaded", timeout=timeout_ms)
    elif reuse_tab and on_x and "/home" not in url:
        page.goto(target, wait_until="domcontentloaded", timeout=timeout_ms)
    time.sleep(2.5)
    if "login" in page.url.lower():
        raise RuntimeError(
            "未检测到 X 登录状态。请：\n"
            "  1. 在 Chrome 中手动登录 x.com，或\n"
            "  2. 更新 data/x.com.cookies.json 后重试"
        )


def ensure_x_home(page: Page, timeout_ms: int = 45000) -> None:
    page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=timeout_ms)
    time.sleep(2.5)
    if "login" in page.url.lower():
        raise RuntimeError("未检测到 X 登录状态，请更新 cookies 或先用 Chrome 登录 x.com")
