"""
Variable in-text marker for auto-generated comments.

Inserts one subtle space (unicode variant) after an existing punctuation mark.
Which space + which anchor position are derived from secret + tweet_id + UTC date.
"""

import hashlib
import os
import re
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from dotenv import load_dotenv

load_dotenv()

# Special space chars only — NOT U+0020, so strip won't eat normal spaces.
MARKERS = (
    "\u00a0",   # no-break space
    "\u2002",   # en space
    "\u2003",   # em space
    "\u2004",   # three-per-em space
    "\u2005",   # four-per-em space
    "\u2006",   # six-per-em space
    "\u2007",   # figure space
    "\u2008",   # punctuation space
    "\u2009",   # thin space
    "\u200a",   # hair space
    "\u202f",   # narrow no-break space
    "\u205f",   # medium mathematical space
    "\u3000",   # ideographic space
)

# Anchor: insert marker immediately after these chars.
PUNCT_RE = re.compile(
    r"[。，！？、；：""''（）《》…—－\-,.!?;:\"\'\(\)\[\]【】「」『』/\\|]"
)


def _marker_secret() -> str:
    return (os.getenv("COMMENT_MARKER_SECRET") or os.getenv("DASHSCOPE_API_KEY") or "xbot").strip()


def _digest(tweet_id: str, when: Optional[datetime] = None) -> str:
    when = when or datetime.now(timezone.utc)
    day = when.strftime("%Y%m%d")
    raw = f"{_marker_secret()}:{tweet_id or '0'}:{day}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def compute_marker(tweet_id: str, when: Optional[datetime] = None) -> str:
    digest = _digest(tweet_id, when)
    idx = int(digest[:8], 16) % len(MARKERS)
    return MARKERS[idx]


def _anchor_insert_positions(text: str) -> List[int]:
    """Indices in text where the marker may be inserted (after punctuation)."""
    positions: List[int] = []
    for m in PUNCT_RE.finditer(text):
        pos = m.end()
        if 0 < pos <= len(text):
            positions.append(pos)
    # dedupe while preserving order
    seen = set()
    unique: List[int] = []
    for p in positions:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique


def strip_existing_marker(text: str) -> str:
    if not text:
        return ""
    return "".join(ch for ch in text if ch not in MARKERS).strip()


def pick_marker_slot(tweet_id: str, when: Optional[datetime] = None) -> Tuple[int, int]:
    """Return (marker_index, anchor_index among eligible punctuation anchors)."""
    digest = _digest(tweet_id, when)
    marker_idx = int(digest[:8], 16) % len(MARKERS)
    anchor_idx = int(digest[8:16], 16)
    return marker_idx, anchor_idx


def apply_auto_marker(comment: str, tweet_id: str) -> Tuple[str, str, int]:
    """
    Insert marker after a punctuation anchor inside the comment.
    Returns (text_with_marker, marker_char, insert_index).
    insert_index is where marker starts in the result string (-1 if appended).
    """
    if os.getenv("COMMENT_MARKER_DISABLED", "").strip().lower() in ("1", "true", "yes"):
        return (comment or "").strip(), "", -1

    base = strip_existing_marker(comment)
    if not base:
        return "", "", -1

    marker_idx, anchor_seed = pick_marker_slot(tweet_id)
    marker = MARKERS[marker_idx]
    anchors = _anchor_insert_positions(base)

    if anchors:
        anchor_pick = anchor_seed % len(anchors)
        insert_at = anchors[anchor_pick]
    else:
        # No punctuation: append at end (rare fallback)
        insert_at = len(base)

    marked = base[:insert_at] + marker + base[insert_at:]
    return marked, marker, insert_at


def marker_index_for(tweet_id: str, when: Optional[datetime] = None) -> int:
    digest = _digest(tweet_id, when)
    return int(digest[:8], 16) % len(MARKERS)
