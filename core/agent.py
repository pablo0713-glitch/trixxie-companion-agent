from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Optional

import aiofiles
import anthropic

from config.settings import Settings
from core.persona import MessageContext, build_system_prompt
from core.rate_limiter import RateLimiter
from core.tools import ToolRegistry
from memory.base import AbstractMemoryStore
from memory.person_map import PersonMap
from memory.schemas import ConversationFile

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 5
# Max turns to pull from each linked-platform conversation for context
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
        client: anthropic.AsyncAnthropic,
        memory: AbstractMemoryStore,
        tool_registry: ToolRegistry,
        rate_limiter: RateLimiter,
        settings: Settings,
        person_map: Optional[PersonMap] = None,
    ) -> None:
        self._client: anthropic.AsyncAnthropic = client
        self._memory = memory
        self._tools = tool_registry
        self._rate_limiter = rate_limiter
        self._settings = settings
        self._person_map = person_map

    async def handle_message(
        self,
        message: str,
        context: MessageContext,
    ) -> AgentResponse:
        # Rate limiting
        if not self._rate_limiter.check(context.user_id):
            return AgentResponse(
                text="Give me a second — you're moving fast. Try again in a moment.",
                was_rate_limited=True,
            )

        # Load history and facts
        history = await self._memory.get_history(context.user_id, context.channel_id)
        facts = await self._memory.get_facts(context.user_id)

        # Load unified cross-platform context and consolidated memory notes
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

        # Append the new user message to history for API call
        messages = list(history) + [{"role": "user", "content": message}]

        # Persist user turn
        await self._memory.append_turn(
            context.user_id, context.channel_id, context.platform, "user", message
        )

        # Run the agentic tool loop
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

        # Persist all assistant turns from the loop
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
        """Load the most recent consolidated memory notes file for a person."""
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
        """
        Pull the most recent CROSS_PLATFORM_TURNS turns from the most recently
        updated conversation file for each linked user_id and format them as text.
        Injected into the system prompt — not the messages array — to avoid
        breaking the alternating-role requirement.
        """
        parts: list[str] = []
        for uid in linked_ids:
            platform = uid.split("_")[0].upper()
            convs: list[ConversationFile] = await self._memory.get_all_conversations(uid)
            if not convs:
                continue
            # Use the most recently updated conversation for this platform
            latest = max(convs, key=lambda c: c.updated_at)
            recent_turns = latest.turns[-CROSS_PLATFORM_TURNS:]
            if not recent_turns:
                continue
            lines = [f"[{platform} — last active {latest.updated_at[:10]}]"]
            for turn in recent_turns:
                role_label = "Trixxie" if turn["role"] == "assistant" else "User"
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
        messages: list[dict],
        system_prompt: str,
        context: MessageContext,
        action_queue: list[dict],
    ) -> tuple[str, list[dict]]:
        """
        Run the Anthropic agentic tool loop.
        Returns (final_text, list_of_assistant_and_tool_result_turns_to_persist).
        """
        tool_definitions = self._tools.get_definitions(context)
        accumulated_turns: list[dict] = []

        for round_num in range(MAX_TOOL_ROUNDS + 1):
            # On the final round, disallow further tool use to force a text reply
            if round_num == MAX_TOOL_ROUNDS:
                tool_choice: dict = {"type": "none"}
            else:
                tool_choice = {"type": "auto"}

            response = await self._client.messages.create(
                model=self._settings.claude_model,
                max_tokens=self._settings.max_tokens,
                system=system_prompt,
                tools=tool_definitions,
                tool_choice=tool_choice,
                messages=messages,
            )

            # Collect the assistant message content blocks
            content_blocks = response.content

            # Build the assistant turn for history
            assistant_turn = {"role": "assistant", "content": content_blocks}
            accumulated_turns.append(assistant_turn)
            messages = messages + [assistant_turn]

            if response.stop_reason == "end_turn":
                # Extract text from content blocks
                text = _extract_text(content_blocks)
                return text, accumulated_turns

            if response.stop_reason == "tool_use":
                # Process all tool calls in this response
                tool_results = []
                for block in content_blocks:
                    if block.type == "tool_use":
                        result = await self._tools.dispatch(
                            block.name, block.input, context, action_queue
                        )
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        })

                tool_result_turn = {"role": "user", "content": tool_results}
                accumulated_turns.append(tool_result_turn)
                messages = messages + [tool_result_turn]
                continue

            # Unexpected stop reason — return whatever text we have
            text = _extract_text(content_blocks)
            return text, accumulated_turns

        # Should not reach here, but just in case
        return "I lost my train of thought. Try asking again.", accumulated_turns


def _extract_text(content_blocks: list) -> str:
    parts = []
    for block in content_blocks:
        if hasattr(block, "type") and block.type == "text":
            parts.append(block.text)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "\n".join(parts).strip()
