"""
Qwen3 comment generator via Alibaba DashScope (OpenAI compatible API).
"""

import os
import time

import httpx
from dotenv import load_dotenv
from openai import OpenAI

from utils.comment_utils import get_comment_system_prompt, build_few_shot_block, build_user_prompt_hint, split_comments

load_dotenv()

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
DASHSCOPE_BASE_URL = os.getenv(
    "DASHSCOPE_BASE_URL",
    "https://dashscope.aliyuncs.com/compatible-mode/v1",
)
DEFAULT_MODEL = os.getenv("DASHSCOPE_MODEL", "qwen-plus")

proxy = (
    os.getenv("DASHSCOPE_PROXY")
    or os.getenv("HTTPS_PROXY")
    or os.getenv("ALL_PROXY")
)

http_client = None
if proxy:
    try:
        http_client = httpx.Client(proxy=proxy, timeout=60.0)
    except Exception as err:
        print(f"[Warning] DashScope 代理不可用 {proxy}: {err}")

MAX_RETRIES = 2
RETRY_DELAY = 1.5


def _get_client() -> OpenAI:
    if not DASHSCOPE_API_KEY:
        raise ValueError("DASHSCOPE_API_KEY not found in environment variables.")
    return OpenAI(
        api_key=DASHSCOPE_API_KEY,
        base_url=DASHSCOPE_BASE_URL,
        http_client=http_client,
        timeout=60.0,
    )


def generate_comments_qwen(post_text: str, author_name: str, num_comments: int = 3) -> list[str]:
    """Generate Chinese comments using Qwen via DashScope."""
    client = _get_client()

    user_prompt = f"""原帖作者：{author_name or '未知'}（仅供参考，不要在评论里 @ 他）

帖子内容：
{post_text}

请针对这条帖子生成 {num_comments} 条不同角度的高质量中文评论。
每条评论单独一行，用 --- 分隔。"""

    few_shot = build_few_shot_block()
    if few_shot:
        user_prompt += "\n\n" + few_shot
    user_prompt += build_user_prompt_hint(post_text)

    models_to_try = [DEFAULT_MODEL, "qwen-plus", "qwen-max", "qwen-turbo"]
    # dedupe while preserving order
    seen = set()
    models = []
    for m in models_to_try:
        if m and m not in seen:
            seen.add(m)
            models.append(m)

    last_error = None
    for model in models:
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": get_comment_system_prompt()},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.85,
                    max_tokens=800,
                )
                content = response.choices[0].message.content.strip()
                return split_comments(content, num_comments)
            except Exception as e:
                last_error = e
                err = str(e).lower()
                if "model" in err and ("not found" in err or "does not exist" in err):
                    break
                if "timeout" in err or "timed out" in err:
                    if attempt < MAX_RETRIES:
                        time.sleep(RETRY_DELAY * (attempt + 1))
                        continue
                break

    raise Exception(
        f"Failed to generate comments via DashScope/Qwen: {last_error} (tried models: {models})"
    )
