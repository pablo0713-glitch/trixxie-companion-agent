from __future__ import annotations

import os
import aiofiles

from core.persona import MessageContext


def _notes_dir_for_user(notes_base: str, user_id: str) -> str:
    safe_uid = user_id.replace("/", "_").replace(":", "_")
    d = os.path.join(notes_base, safe_uid)
    os.makedirs(d, exist_ok=True)
    return d


def _note_path(notes_base: str, user_id: str, title: str) -> str:
    safe_title = title.replace("/", "_").replace("\\", "_").replace(":", "_")
    return os.path.join(_notes_dir_for_user(notes_base, user_id), f"{safe_title}.txt")


async def handle_note_write(
    tool_input: dict,
    context: MessageContext,
    notes_base: str,
) -> str:
    title = tool_input.get("title", "").strip()
    content = tool_input.get("content", "").strip()

    if not title:
        return "A title is required to save a note."
    if not content:
        return "Content cannot be empty."

    path = _note_path(notes_base, context.user_id, title)
    async with aiofiles.open(path, "w", encoding="utf-8") as f:
        await f.write(content)

    return f"Note '{title}' saved."


async def handle_note_read(
    tool_input: dict,
    context: MessageContext,
    notes_base: str,
) -> str:
    title = tool_input.get("title", "").strip()
    if not title:
        return "Specify a note title to read."

    path = _note_path(notes_base, context.user_id, title)
    if not os.path.exists(path):
        return f"No note found with title '{title}'."

    async with aiofiles.open(path, "r", encoding="utf-8") as f:
        content = await f.read()
    return f"Note '{title}':\n{content}"


async def handle_note_list(
    tool_input: dict,
    context: MessageContext,
    notes_base: str,
) -> str:
    d = _notes_dir_for_user(notes_base, context.user_id)
    try:
        files = [f[:-4] for f in os.listdir(d) if f.endswith(".txt")]
    except OSError:
        files = []

    if not files:
        return "No notes saved yet."

    return "Saved notes:\n" + "\n".join(f"- {t}" for t in sorted(files))
