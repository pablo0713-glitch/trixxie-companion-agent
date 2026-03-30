from __future__ import annotations

DISCORD_LIMIT = 2000


def chunk_text(text: str, limit: int = DISCORD_LIMIT) -> list[str]:
    """Split text into chunks that fit within Discord's message limit.

    Tries to break at paragraph or sentence boundaries.
    """
    if len(text) <= limit:
        return [text]

    chunks = []
    remaining = text

    while len(remaining) > limit:
        # Try paragraph break first
        idx = remaining.rfind("\n\n", 0, limit)
        if idx > limit // 3:
            chunks.append(remaining[: idx + 2].rstrip())
            remaining = remaining[idx + 2 :].lstrip()
            continue

        # Try sentence break
        for sep in (". ", "! ", "? ", "\n"):
            idx = remaining.rfind(sep, 0, limit)
            if idx > limit // 3:
                chunks.append(remaining[: idx + 1].rstrip())
                remaining = remaining[idx + 1 :].lstrip()
                break
        else:
            # Hard cut
            chunks.append(remaining[:limit])
            remaining = remaining[limit:]

    if remaining:
        chunks.append(remaining)

    return chunks
