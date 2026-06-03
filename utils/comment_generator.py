"""
Unified comment generator: DashScope Qwen -> local fallback.
"""

import os

from dotenv import load_dotenv

from utils.comment_fallback import generate_comment_fallback
from utils.qwen_generator import generate_comments_qwen

load_dotenv()


def generate_comments(post_text: str, author_name: str, num_comments: int = 3) -> list[str]:
    """Generate Chinese comments for an X post."""
    errors: list[str] = []

    if os.getenv("DASHSCOPE_API_KEY"):
        try:
            return generate_comments_qwen(post_text, author_name, num_comments)
        except Exception as e:
            errors.append(f"Qwen: {e}")

    if errors:
        print(f"[comment_generator] DashScope 失败，使用本地模板。详情: {' | '.join(errors)}")

    return generate_comment_fallback(post_text, author_name, num_comments)
