from __future__ import annotations

SL_CHAT_LIMIT = 1023
REPLY_HARD_CAP = 4000      # SL: LSL send_chunked splits this into multiple IMs (≤1000 chars each)
OPENSIM_REPLY_CAP = 1800   # OpenSim: default llHTTPRequest response body limit is 2048 bytes

# Unicode → ASCII replacements for SL compatibility
_UNICODE_MAP = str.maketrans({
    "\u2018": "'",   # left single quotation mark
    "\u2019": "'",   # right single quotation mark
    "\u201c": '"',   # left double quotation mark
    "\u201d": '"',   # right double quotation mark
    "\u2014": "--",  # em dash
    "\u2013": "-",   # en dash
    "\u2026": "...", # ellipsis
    "\u00a0": " ",   # non-breaking space
    "\u2022": "-",   # bullet
})


def trim_for_sl(text: str) -> str:
    """Trim text to SL_CHAT_LIMIT, breaking at a sentence boundary if possible."""
    if len(text) <= SL_CHAT_LIMIT:
        return text

    # Try to break at last sentence boundary within limit
    cutoff = text[:SL_CHAT_LIMIT]
    for sep in (". ", "! ", "? ", "\n"):
        idx = cutoff.rfind(sep)
        if idx > SL_CHAT_LIMIT // 2:
            return cutoff[: idx + 1].rstrip()

    return cutoff[:SL_CHAT_LIMIT - 3] + "..."


def cap_reply(text: str, grid: str = "sl") -> str:
    """Normalize Unicode and apply a grid-aware hard cap.
    OpenSim's default llHTTPRequest response body limit is 2048 bytes, so replies
    are capped at 1800 chars to leave room for the JSON envelope.
    SL chunking (send_chunked in LSL) handles splitting for longer SL replies."""
    text = text.translate(_UNICODE_MAP)
    # LSL cannot handle non-BMP characters (emoji, U+10000+); strip them to avoid
    # garbled bytes like ð appearing in local chat output.
    text = "".join(c for c in text if ord(c) <= 0xFFFF)
    cap = OPENSIM_REPLY_CAP if grid == "opensim" else REPLY_HARD_CAP
    if len(text) > cap:
        text = text[:cap]
    return text
