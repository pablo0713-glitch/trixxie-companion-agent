from __future__ import annotations

SL_CHAT_LIMIT = 1023
REPLY_HARD_CAP = 4000   # LSL send_chunked splits this into multiple IMs (≤1000 chars each)

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


def cap_reply(text: str) -> str:
    """Normalize Unicode and apply a hard cap. Chunking into multiple IMs is
    handled on the LSL side by send_chunked(), so we do not trim to SL_CHAT_LIMIT here."""
    text = text.translate(_UNICODE_MAP)
    if len(text) > REPLY_HARD_CAP:
        text = text[:REPLY_HARD_CAP]
    return text
