from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Optional

import time

import aiofiles

from config.settings import Settings
from core.model_adapter import ModelAdapter
from core.persona import MessageContext, build_system_prompt_blocks, get_agent_config
from core.rate_limiter import RateLimiter
from core.tools import ToolRegistry
from memory.base import AbstractMemoryStore
from memory.person_map import PersonMap
from memory.schemas import ConversationFile

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 5
CROSS_PLATFORM_TURNS = 15


@dataclass
class AgentResponse:
    text: str
    sl_actions: list[dict] = field(default_factory=list)
    was_rate_limited: bool = False
    was_refused: bool = False


class AgentCore:
    def __init__(
        self,
        adapter: ModelAdapter,
        memory: AbstractMemoryStore,
        tool_registry: ToolRegistry,
        rate_limiter: RateLimiter,
        settings: Settings,
        person_map: Optional[PersonMap] = None,
    ) -> None:
        self._adapter = adapter
        self._memory = memory
        self._tools = tool_registry
        self._rate_limiter = rate_limiter
        self._settings = settings
        self._person_map = person_map
        self._last_prompt: dict[str, str] = {}
        self._last_exchange: dict[str, dict] = {}

    async def handle_message(self, message: str, context: MessageContext) -> AgentResponse:
        if not self._rate_limiter.check(context.user_id):
            return AgentResponse(
                text="Give me a second — you're moving fast. Try again in a moment.",
                was_rate_limited=True,
            )

        history = await self._memory.get_history(context.user_id, context.channel_id)
        facts = await self._memory.get_facts(context.user_id)

        memory_notes = ""
        cross_platform_context = ""
        if self._person_map:
            person_id = self._person_map.get_person_id(context.user_id)
            if person_id:
                memory_notes = await self._load_memory_notes(person_id)
            linked_ids = self._person_map.get_linked_ids(context.user_id)
            if linked_ids:
                cross_platform_context = await self._load_cross_platform_context(linked_ids)

        system_blocks = build_system_prompt_blocks(context, facts, memory_notes, cross_platform_context)
        # Flatten for debug display (blocks are passed directly to the adapter)
        system_flat = "\n\n".join(b["text"] for b in system_blocks)
        self._last_prompt[context.user_id] = system_flat
        messages = list(history) + [{"role": "user", "content": message}]

        await self._memory.append_turn(
            context.user_id, context.channel_id, context.platform, "user", message
        )

        sl_action_queue: list[dict] = []
        try:
            reply_text, assistant_turns = await self._run_tool_loop(
                messages, system_blocks, context, sl_action_queue
            )
            self._last_exchange[context.user_id] = {
                "ts": time.time(),
                "platform": context.platform,
                "user_message": message,
                "system_prompt": system_flat,
                "messages": messages,
                "reply_text": reply_text,
                "assistant_turns": assistant_turns,
            }
        except Exception as exc:
            logger.exception("Error in tool loop: %s", exc)
            return AgentResponse(
                text="Something went sideways on my end. Give me a moment and try again.",
            )

        for turn in assistant_turns:
            await self._memory.append_turn(
                context.user_id,
                context.channel_id,
                context.platform,
                turn["role"],
                turn["content"],
            )

        return AgentResponse(text=reply_text, sl_actions=sl_action_queue)

    def get_last_prompt(self, user_id: str) -> str | None:
        return self._last_prompt.get(user_id)

    def get_last_exchange(self, user_id: str) -> dict | None:
        return self._last_exchange.get(user_id)

    def all_tracked_users(self) -> list[str]:
        return list(self._last_prompt.keys())

    async def _load_memory_notes(self, person_id: str) -> str:
        notes_dir = os.path.join(self._settings.notes_dir, person_id)
        if not os.path.exists(notes_dir):
            return ""
        files = sorted(
            f for f in os.listdir(notes_dir)
            if f.startswith("memories_") and f.endswith(".md")
            and not f.startswith("memories_summary_")
        )
        if not files:
            return ""
        latest_file = files[-1]
        # e.g. "memories_2026-04-07.md" → "2026-04-07"
        date_part = latest_file[len("memories_"):-len(".md")]
        summary_path = os.path.join(notes_dir, f"memories_summary_{date_part}.md")

        if os.path.exists(summary_path):
            try:
                async with aiofiles.open(summary_path, "r", encoding="utf-8") as f:
                    return await f.read()
            except OSError:
                pass

        try:
            async with aiofiles.open(os.path.join(notes_dir, latest_file), "r", encoding="utf-8") as f:
                full_notes = await f.read()
        except OSError:
            return ""

        if not full_notes.strip():
            return ""

        summary = await self._adapter.create_simple(
            system=(
                "Summarize the following memory notes into 3–5 bullet points. "
                "Keep the most personally relevant facts. "
                "Max 500 characters total. "
                "Write in second person as context for an AI: "
                "'User is...', 'User prefers...', etc."
            ),
            messages=[{"role": "user", "content": full_notes}],
            max_tokens=200,
        )

        if summary:
            try:
                async with aiofiles.open(summary_path, "w", encoding="utf-8") as f:
                    await f.write(summary)
            except OSError as exc:
                logger.warning("Failed to cache memory summary: %s", exc)

        return summary or full_notes[:500]

    async def _load_cross_platform_context(self, linked_ids: list[str]) -> str:
        agent_name = get_agent_config().get("agent_name", "Agent")
        parts: list[str] = []
        for uid in linked_ids:
            platform = uid.split("_")[0].upper()
            convs: list[ConversationFile] = await self._memory.get_all_conversations(uid)
            if not convs:
                continue
            latest = max(convs, key=lambda c: c.updated_at)
            recent_turns = latest.turns[-CROSS_PLATFORM_TURNS:]
            if not recent_turns:
                continue

            # Check per-uid summary cache (invalidated when conversation updated_at changes)
            cache_path = os.path.join(self._settings.memory_dir, uid, "_cross_summary.txt")
            cached_summary = None
            if os.path.exists(cache_path):
                try:
                    async with aiofiles.open(cache_path, "r", encoding="utf-8") as f:
                        cache_content = await f.read()
                    cache_ts, _, cached_text = cache_content.partition("\n")
                    if cache_ts == latest.updated_at:
                        cached_summary = cached_text
                except OSError:
                    pass

            if cached_summary:
                parts.append(f"[{platform} — last active {latest.updated_at[:10]}]\n{cached_summary}")
                continue

            # Build transcript and summarize
            transcript_lines = []
            for turn in recent_turns:
                role_label = agent_name if turn["role"] == "assistant" else "User"
                content = turn.get("content", "")
                if isinstance(content, list):
                    texts = [
                        b.get("text", "")
                        for b in content
                        if isinstance(b, dict) and b.get("type") == "text"
                    ]
                    content = " ".join(t for t in texts if t)
                if content:
                    transcript_lines.append(f"{role_label}: {content[:300]}")

            if not transcript_lines:
                continue

            transcript = "\n".join(transcript_lines)
            summary = await self._adapter.create_simple(
                system=(
                    "Summarize this conversation excerpt in 1–3 sentences. "
                    "Focus on what topics were discussed and the overall tone. "
                    "Max 200 characters."
                ),
                messages=[{"role": "user", "content": transcript}],
                max_tokens=80,
            )

            if summary:
                try:
                    async with aiofiles.open(cache_path, "w", encoding="utf-8") as f:
                        await f.write(f"{latest.updated_at}\n{summary}")
                except OSError as exc:
                    logger.warning("Failed to cache cross-platform summary: %s", exc)

            summary = summary or transcript[:200]
            parts.append(f"[{platform} — last active {latest.updated_at[:10]}]\n{summary}")

        return "\n\n".join(parts)

    async def _run_tool_loop(
        self,
        messages: list,
        system_blocks: list[dict],
        context: MessageContext,
        action_queue: list[dict],
    ) -> tuple[str, list[dict]]:
        tool_definitions = self._tools.get_definitions(context)
        accumulated_turns: list[dict] = []

        for round_num in range(MAX_TOOL_ROUNDS + 1):
            tool_choice: dict = {"type": "none"} if round_num == MAX_TOOL_ROUNDS else {"type": "auto"}

            response = await self._adapter.create(
                system=system_blocks,
                messages=messages,
                tools=tool_definitions,
                tool_choice=tool_choice,
                max_tokens=self._settings.max_tokens,
            )

            assistant_turn = {"role": "assistant", "content": response.history_content}
            accumulated_turns.append(assistant_turn)
            messages = messages + [assistant_turn]

            if response.stop_reason == "end_turn":
                return response.text, accumulated_turns

            if response.stop_reason == "tool_use":
                tool_results = []
                for tc in response.tool_calls:
                    result = await self._tools.dispatch(tc.name, tc.input, context, action_queue)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "content": result,
                    })
                tool_result_turn = {"role": "user", "content": tool_results}
                accumulated_turns.append(tool_result_turn)
                messages = messages + [tool_result_turn]
                continue

            return response.text, accumulated_turns

        return "I lost my train of thought. Try asking again.", accumulated_turns
