from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Optional

import aiofiles

from config.settings import Settings
from core.model_adapter import ModelAdapter
from core.persona import MessageContext, build_system_prompt, get_agent_config
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

        system_prompt = build_system_prompt(context, facts, memory_notes, cross_platform_context)
        messages = list(history) + [{"role": "user", "content": message}]

        await self._memory.append_turn(
            context.user_id, context.channel_id, context.platform, "user", message
        )

        sl_action_queue: list[dict] = []
        try:
            reply_text, assistant_turns = await self._run_tool_loop(
                messages, system_prompt, context, sl_action_queue
            )
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

    async def _load_memory_notes(self, person_id: str) -> str:
        notes_dir = os.path.join(self._settings.notes_dir, person_id)
        if not os.path.exists(notes_dir):
            return ""
        files = sorted(
            f for f in os.listdir(notes_dir)
            if f.startswith("memories_") and f.endswith(".md")
        )
        if not files:
            return ""
        try:
            async with aiofiles.open(os.path.join(notes_dir, files[-1]), "r", encoding="utf-8") as f:
                return await f.read()
        except OSError:
            return ""

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
            lines = [f"[{platform} — last active {latest.updated_at[:10]}]"]
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
                    lines.append(f"{role_label}: {content[:300]}")
            if len(lines) > 1:
                parts.append("\n".join(lines))
        return "\n\n".join(parts)

    async def _run_tool_loop(
        self,
        messages: list,
        system_prompt: str,
        context: MessageContext,
        action_queue: list[dict],
    ) -> tuple[str, list[dict]]:
        tool_definitions = self._tools.get_definitions(context)
        accumulated_turns: list[dict] = []

        for round_num in range(MAX_TOOL_ROUNDS + 1):
            tool_choice: dict = {"type": "none"} if round_num == MAX_TOOL_ROUNDS else {"type": "auto"}

            response = await self._adapter.create(
                system=system_prompt,
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
