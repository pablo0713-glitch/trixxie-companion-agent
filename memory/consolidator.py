from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

import aiofiles
import anthropic

from memory.file_store import FileMemoryStore
from memory.person_map import PersonMap
from memory.schemas import ConversationFile

logger = logging.getLogger(__name__)

# Trigger consolidation when any single conversation file exceeds this many turns.
CONSOLIDATION_THRESHOLD = 40

# How many turns to keep in each conversation file after consolidation.
KEEP_TURNS_AFTER = 10


class MemoryConsolidator:
    """
    Periodically reads Trixxie's conversation files for each known person,
    asks Claude to extract what's worth remembering, saves the result as a
    Markdown note under {notes_dir}/{person_id}/memories_{date}.md, then
    trims the source conversation files.

    Cross-platform consolidation: all user_ids linked to the same person
    (Discord + SL) are read together so the notes reflect the full picture.
    """

    def __init__(
        self,
        client: anthropic.AsyncAnthropic,
        memory_store: FileMemoryStore,
        person_map: PersonMap,
        notes_dir: str,
        model: str,
        threshold: int = CONSOLIDATION_THRESHOLD,
        keep_turns: int = KEEP_TURNS_AFTER,
    ) -> None:
        self._client = client
        self._store = memory_store
        self._person_map = person_map
        self._notes_dir = notes_dir
        self._model = model
        self._threshold = threshold
        self._keep_turns = keep_turns

    async def run_all(self) -> None:
        """Check every known person and consolidate if the threshold is exceeded."""
        for person_id in self._person_map.all_persons():
            try:
                await self._check_and_consolidate(person_id)
            except Exception:
                logger.exception("Consolidation failed for person '%s'", person_id)

    # ------------------------------------------------------------------ internals

    async def _check_and_consolidate(self, person_id: str) -> None:
        user_ids = self._person_map.get_person_user_ids(person_id)
        all_convs: list[ConversationFile] = []
        for uid in user_ids:
            all_convs.extend(await self._store.get_all_conversations(uid))

        if not all_convs:
            return

        max_turns_in_file = max(len(c.turns) for c in all_convs)
        if max_turns_in_file < self._threshold:
            return

        total = sum(len(c.turns) for c in all_convs)
        logger.info(
            "Consolidating memory for '%s': %d files, %d total turns",
            person_id, len(all_convs), total,
        )

        await self._consolidate(person_id, all_convs)

        for uid in user_ids:
            convs = await self._store.get_all_conversations(uid)
            for conv in convs:
                await self._store.trim_history(uid, conv.channel_id, self._keep_turns)

        logger.info("Consolidation complete for '%s'. Files trimmed to %d turns.", person_id, self._keep_turns)

    async def _consolidate(self, person_id: str, convs: list[ConversationFile]) -> None:
        transcript = _build_transcript(convs)
        if not transcript.strip():
            return

        notes_text = await self._ask_claude(person_id, transcript)
        if not notes_text:
            return

        person_notes_dir = os.path.join(self._notes_dir, person_id)
        os.makedirs(person_notes_dir, exist_ok=True)

        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = os.path.join(person_notes_dir, f"memories_{date_str}.md")

        async with aiofiles.open(path, "w", encoding="utf-8") as f:
            await f.write(notes_text)

        logger.info("Memory notes written → %s", path)

    async def _ask_claude(self, person_id: str, transcript: str) -> str:
        prompt = (
            f"You are Trixxie Carissa. You're reviewing your conversation logs "
            f"with {person_id} across Second Life and Discord.\n\n"
            f"Here are the conversations:\n\n{transcript}\n\n"
            f"Write your personal memory notes about {person_id}. Include:\n"
            f"- Important facts about them (name, preferences, context)\n"
            f"- Their aesthetic tastes and interests\n"
            f"- Ongoing projects or topics you've discussed\n"
            f"- Things that clearly matter to them\n"
            f"- Recurring themes, inside references, or anything to carry forward\n"
            f"- How they use each platform and what they tend to talk to you about there\n\n"
            f"Write in first person as Trixxie, as if writing in a personal journal. "
            f"Be selective — only keep what is genuinely worth remembering. "
            f"Do not include tool calls, raw JSON, or system messages."
        )

        response = await self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text if response.content else ""


# ------------------------------------------------------------------ helpers

def _build_transcript(convs: list[ConversationFile]) -> str:
    """Format all conversation files into a readable transcript for Claude."""
    parts: list[str] = []

    for conv in sorted(convs, key=lambda c: c.updated_at):
        header = f"[{conv.platform.upper()} | channel: {conv.channel_id} | last updated: {conv.updated_at[:10]}]"
        lines = [header]

        for turn in conv.turns:
            role_label = "Trixxie" if turn["role"] == "assistant" else "User"
            content = turn.get("content", "")

            if isinstance(content, list):
                # Extract only text blocks; skip tool_use / tool_result noise
                texts = [
                    b.get("text", "")
                    for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                ]
                content = " ".join(t for t in texts if t)

            if content:
                # Truncate very long turns to keep the prompt manageable
                if len(content) > 500:
                    content = content[:500] + "…"
                lines.append(f"{role_label}: {content}")

        if len(lines) > 1:
            parts.append("\n".join(lines))

    return "\n\n---\n\n".join(parts)
