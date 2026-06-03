"""
Fallback comment generator when LLM API is unavailable.
"""

import random
import re
from typing import List

from utils.comment_utils import sanitize_comment

TOPIC_HINTS = {
    "AI": ["AI", "人工智能", "大模型", "GPT", "Claude", "Grok", "LLM", "模型", "Agent"],
    "工具": ["工具", "效率", "生产力", "App", "软件", "插件"],
    "投资": ["股票", "美股", "币", "BTC", "ETH", "投资", "建仓", "ETF"],
    "生活": ["生活", "日常", "分享", "感悟", "经历"],
    "劳动": ["外卖", "骑手", "快递", "算法", "平台", "压榨", "送餐", "美团", "饿了么", "滴滴"],
}


def _detect_topics(text: str) -> List[str]:
    lower = text.lower()
    found = []
    for topic, kws in TOPIC_HINTS.items():
        if any(kw.lower() in lower or kw in text for kw in kws):
            found.append(topic)
    return found or ["通用"]


def _short_summary(text: str, max_len: int = 28) -> str:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    core = lines[0] if lines else text
    core = re.sub(r"https?://\S+", "", core)
    core = re.sub(r"@\w+", "", core).strip()
    if len(core) > max_len:
        return core[: max_len - 1] + "…"
    return core or "这个视角"


def generate_comment_fallback(post_text: str, author_name: str, num_comments: int = 1) -> List[str]:
    """Generate simple but post-related Chinese comments without API."""
    summary = _short_summary(post_text)
    topic = _detect_topics(post_text)[0]

    pools = {
        "AI": [
            f"「{summary}」这个点说得很到位，AI 这块变化确实太快了，我也在持续跟进",
            f"{summary} 这个角度我之前没细想过，挺有启发的",
            f"现在做 AI 相关的事，{summary} 几乎是绕不开的话题",
        ],
        "工具": [
            f"「{summary}」这个思路很实用，已收藏",
            f"{summary} 正是我最近在找的解法",
            f"这条工具流很丝滑，{summary} 确实能省不少时间",
        ],
        "投资": [
            f"「{summary}」这个观察有意思，值得再跟踪一下",
            f"{summary} 这块逻辑挺清晰，我会继续研究",
            f"这个角度给了我不一样的参考，{summary} 值得琢磨",
        ],
        "生活": [
            f"「{summary}」看得很有共鸣",
            f"{summary} 让我也想到了类似的事",
            f"被这条触动了，{summary} 说到了点子上",
        ],
        "劳动": [
            "多给五分钟有个屁用，只会多抢几单，该闯还是闯。跟算法没半毛钱关系，就是只顾自己利益",
            "他妈的别什么都甩锅算法，这套规则很大程度是骑手自己卷出来的，改时间解决不了傻逼问题",
            "这逻辑也是够傻逼的，把人全洗成受害者，根子不在平台那几个参数",
        ],
        "通用": [
            f"「{summary}」信息密度很高，值得反复看",
            f"{summary} 给了我新的启发",
            f"说得很好，{summary} 这个点我之前忽略了",
        ],
    }

    candidates = [sanitize_comment(c) for c in pools.get(topic, pools["通用"])]
    random.shuffle(candidates)
    return candidates[:num_comments]
