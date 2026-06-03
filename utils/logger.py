"""
Published comments logger
"""

import json
import os
from datetime import datetime, timezone
from typing import List, Dict, Optional

PUBLISHED_LOG_PATH = "data/published_log.json"


def _load_log() -> List[Dict]:
    if not os.path.exists(PUBLISHED_LOG_PATH):
        return []
    try:
        with open(PUBLISHED_LOG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_log(logs: List[Dict]):
    os.makedirs(os.path.dirname(PUBLISHED_LOG_PATH), exist_ok=True)
    with open(PUBLISHED_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(logs, f, ensure_ascii=False, indent=2)


def mark_post_as_replied(
    tweet_id: str,
    tweet_url: str = "",
    author: str = "",
    source: str = "manual",
) -> bool:
    """Record that we already replied to this tweet (bot, manual, or sync). Returns True if newly added."""
    if not tweet_id or has_published_for_post(tweet_id):
        return False
    logs = _load_log()
    logs.append(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tweet_id": tweet_id,
            "tweet_url": tweet_url or f"https://x.com/i/status/{tweet_id}",
            "author": author,
            "comment": f"[{source}]",
            "source": source,
        }
    )
    _save_log(logs)
    return True


def log_published_comment(
    tweet_id: str,
    tweet_url: str,
    comment: str,
    author: str,
    marker: str = "",
    marker_pos: int = -1,
) -> Dict:
    """Record a successfully published comment."""
    logs = _load_log()
    
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tweet_id": tweet_id,
        "tweet_url": tweet_url,
        "author": author,
        "comment": comment,
        "source": "bot",
    }
    if marker:
        entry["marker"] = marker
        entry["auto_marked"] = True
        if marker_pos >= 0:
            entry["marker_pos"] = marker_pos
    logs.append(entry)
    _save_log(logs)
    return entry


def get_published_log(limit: int = 50) -> List[Dict]:
    """Get recent published records."""
    logs = _load_log()
    return sorted(logs, key=lambda x: x.get("timestamp", ""), reverse=True)[:limit]


def is_already_published(tweet_id: str, comment: str) -> bool:
    """Check if this exact comment was already published on this tweet."""
    logs = _load_log()
    for entry in logs:
        if entry.get("tweet_id") == tweet_id and entry.get("comment") == comment:
            return True
    return False


def has_published_for_post(tweet_id: str) -> bool:
    """Check if any comment has already been published for this tweet/post."""
    if not tweet_id:
        return False
    logs = _load_log()
    for entry in logs:
        if entry.get("tweet_id") == tweet_id:
            return True
    return False
