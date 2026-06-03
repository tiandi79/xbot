"""Shared helpers for comment generation."""

import os
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STYLE_PATH = PROJECT_ROOT / "data" / "comment_style.md"
DEFAULT_EXAMPLES_PATH = PROJECT_ROOT / "data" / "comment_style_examples.md"

_PROMPT_WRAPPER = """你是 X（Twitter）中文评论写作助手。
下面「用户风格说明」是账号主人的真实立场和语气，必须严格遵守。
Technical rules（代码层，不可违反）：
- 禁止 @ 任何人
- 每条 60-110 字
- emoji 最多 1 个
- 只输出评论正文，不要标题或「评论：」前缀
"""


def _resolve_path(env_key: str, default: Path) -> Path:
    raw = (os.getenv(env_key) or "").strip()
    if not raw:
        return default
    p = Path(raw)
    return p if p.is_absolute() else PROJECT_ROOT / p


def load_style_text() -> str:
    path = _resolve_path("COMMENT_STYLE_PATH", DEFAULT_STYLE_PATH)
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception as e:
        print(f"[comment_utils] Warning: cannot read style file {path}: {e}")
        return ""


def load_style_examples(max_examples: int = 4) -> list[str]:
    """Parse few-shot blocks from comment_style_examples.md."""
    path = _resolve_path("COMMENT_STYLE_EXAMPLES_PATH", DEFAULT_EXAMPLES_PATH)
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return []

    blocks: list[str] = []
    for block in text.split("---"):
        block = block.strip()
        if not block or block.startswith("#"):
            continue
        if "在此粘贴" in block or "在此写你会" in block:
            continue
        if "我的评论：" not in block and "我的评论:" not in block:
            continue
        blocks.append(block)

    return blocks[-max_examples:] if len(blocks) > max_examples else blocks


def build_comment_system_prompt() -> str:
    style = load_style_text()
    parts = [_PROMPT_WRAPPER.strip()]
    if style:
        parts.append("## 用户风格说明\n\n" + style)
    extra = (os.getenv("COMMENT_STYLE_EXTRA") or "").strip()
    if extra:
        parts.append("## 额外补充\n\n" + extra)
    return "\n\n".join(parts)


def build_user_prompt_hint(post_text: str) -> str:
    """Per-post generation hint."""
    if not post_text:
        return ""
    t = post_text.lower()
    help_kw = (
        "看不懂", "没看懂", "不理解", "不明白", "求解释", "求科普", "谁能讲",
        "有谁能", "什么意思", "啥意思", "怎么回事", "请教", "求助", "有没有懂",
        "don't understand", "confused", "explain",
    )
    if any(k in post_text or k in t for k in help_kw):
        return (
            "\n\n【本条特别提示】原帖是在求助或表示看不懂，请用大白话帮忙讲清楚，"
            "禁止嘲讽「看不懂还发」、禁止骂提问者脑子有问题。"
        )
    return ""


def build_few_shot_block() -> str:
    examples = load_style_examples()
    if not examples:
        return ""
    lines = ["参考以下范例（模仿语气、立场和脏字用法，不要照抄）："]
    for i, ex in enumerate(examples, 1):
        lines.append(f"\n【范例 {i}】\n{ex}")
    return "\n".join(lines)


def get_comment_system_prompt() -> str:
    """Build system prompt on each call so style file edits apply without restart."""
    return build_comment_system_prompt()


# 兼容旧引用
COMMENT_SYSTEM_PROMPT = get_comment_system_prompt()


def sanitize_comment(text: str) -> str:
    """Strip leading @mentions and extra whitespace."""
    s = (text or "").strip()
    s = re.sub(r"^(@\w+\s*)+", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def split_comments(content: str, num_comments: int) -> list[str]:
    comments = [sanitize_comment(c) for c in content.split("---") if c.strip()]
    while len(comments) < num_comments:
        comments.append("这逻辑也是够傻逼的，换几个说法还是那回事。")
    return comments[:num_comments]
