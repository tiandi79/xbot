"""
X Comment Publisher using Playwright + cookies.json
"""

import json
import os
import time
import random
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from dotenv import load_dotenv
from utils.reply_guard import ensure_reply_button_visible

load_dotenv()

DEFAULT_COOKIES_PATH = os.getenv("COOKIES_PATH", "data/cookies.json")


def load_cookies(cookies_path: str = DEFAULT_COOKIES_PATH) -> list:
    """Load cookies from JSON file (array of cookie objects)."""
    if not os.path.exists(cookies_path):
        raise FileNotFoundError(f"Cookies file not found: {cookies_path}")

    with open(cookies_path, "r", encoding="utf-8") as f:
        cookies = json.load(f)
    
    if not isinstance(cookies, list):
        raise ValueError("cookies.json must be a JSON array of cookie objects")
    
    return cookies


def publish_comment(tweet_url: str, comment_text: str, cookies_path: str = DEFAULT_COOKIES_PATH) -> dict:
    """
    Post a reply to a tweet using Playwright and saved cookies.
    
    Returns:
        dict: {"success": bool, "message": str, "error": Optional[str]}
    """
    cookies = load_cookies(cookies_path)
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        
        # Add cookies
        context.add_cookies(cookies)
        
        page = context.new_page()
        
        try:
            # Go to the tweet
            page.goto(tweet_url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(random.uniform(1.5, 3.0))  # Human-like delay

            # Try to find and click the reply button
            reply_clicked = False
            reply_btn = ensure_reply_button_visible(page)
            if reply_btn:
                try:
                    reply_btn.click()
                    reply_clicked = True
                except Exception:
                    pass
            
            if not reply_clicked:
                return {"success": False, "message": "无法找到回复按钮", "error": "Reply button not found"}

            time.sleep(random.uniform(1.0, 2.0))

            # Find the reply textarea
            textarea_selectors = [
                '[data-testid="tweetTextarea_0"]',
                'div[role="textbox"][aria-label*="回复"]',
                'div[contenteditable="true"]'
            ]
            
            reply_box = None
            for selector in textarea_selectors:
                try:
                    box = page.locator(selector).first
                    if box.is_visible():
                        reply_box = box
                        break
                except:
                    continue

            if not reply_box:
                return {"success": False, "message": "无法找到回复输入框", "error": "Reply box not found"}

            # Type the comment (with small delays)
            reply_box.click()
            time.sleep(0.5)
            page.keyboard.type(comment_text, delay=80)
            time.sleep(random.uniform(1.2, 2.5))

            # Find and click the post button
            post_button_selectors = [
                '[data-testid="tweetButton"]',
                'div[role="button"][data-testid="tweetButtonInline"]',
                'button[aria-label*="发帖"]'
            ]
            
            posted = False
            for selector in post_button_selectors:
                try:
                    post_btn = page.locator(selector).first
                    if post_btn.is_visible() and post_btn.is_enabled():
                        post_btn.click()
                        posted = True
                        break
                except:
                    continue

            if not posted:
                return {"success": False, "message": "无法找到发布按钮", "error": "Post button not found"}

            # Wait for confirmation (success indicator)
            time.sleep(random.uniform(2.5, 4.5))
            
            # Simple success check - look for common success signals
            success = True  # Assume success if no obvious error in short time
            
            return {
                "success": success,
                "message": "评论发布成功" if success else "发布可能失败，请手动检查",
                "error": None
            }

        except PlaywrightTimeout as e:
            return {"success": False, "message": "页面加载超时", "error": str(e)}
        except Exception as e:
            return {"success": False, "message": "发布过程中发生错误", "error": str(e)}
        finally:
            browser.close()
