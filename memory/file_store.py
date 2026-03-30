from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Any

import aiofiles

from memory.base import AbstractMemoryStore
from memory.schemas import ConversationFile, FactsFile


class FileMemoryStore(AbstractMemoryStore):
    """Phase 1 memory: JSON files on disk, one per user/channel pair."""

    def __init__(self, memory_dir: str, max_history: int) -> None:
        self._memory_dir = memory_dir
        self._max_history = max_history
        # Per-(user_id, channel_id) locks to prevent write races
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}

    # ------------------------------------------------------------------ paths

    def _conv_path(self, user_id: str, channel_id: str) -> str:
        user_dir = os.path.join(self._memory_dir, _safe(user_id))
        os.makedirs(user_dir, exist_ok=True)
        return os.path.join(user_dir, f"{_safe(channel_id)}.json")

    def _facts_path(self, user_id: str) -> str:
        user_dir = os.path.join(self._memory_dir, _safe(user_id))
        os.makedirs(user_dir, exist_ok=True)
        return os.path.join(user_dir, "_facts.json")

    def _lock(self, user_id: str, channel_id: str) -> asyncio.Lock:
        key = (user_id, channel_id)
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    # -------------------------------------------------------------- history

    async def get_history(self, user_id: str, channel_id: str) -> list[dict[str, Any]]:
        path = self._conv_path(user_id, channel_id)
        data = await _read_json(path)
        if data is None:
            return []
        cf = ConversationFile.model_validate(data)
        return cf.turns

    async def append_turn(
        self,
        user_id: str,
        channel_id: str,
        platform: str,
        role: str,
        content: str | list[Any],
    ) -> None:
        async with self._lock(user_id, channel_id):
            path = self._conv_path(user_id, channel_id)
            data = await _read_json(path)
            if data is None:
                cf = ConversationFile(
                    user_id=user_id, channel_id=channel_id, platform=platform
                )
            else:
                cf = ConversationFile.model_validate(data)

            cf.turns.append({"role": role, "content": _serialize_content(content)})
            cf.updated_at = _now()

            if len(cf.turns) > self._max_history:
                cf.turns = cf.turns[-self._max_history :]

            await _write_json(path, _cf_to_dict(cf))

    async def trim_history(self, user_id: str, channel_id: str, max_turns: int) -> None:
        async with self._lock(user_id, channel_id):
            path = self._conv_path(user_id, channel_id)
            data = await _read_json(path)
            if data is None:
                return
            cf = ConversationFile.model_validate(data)
            if len(cf.turns) > max_turns:
                cf.turns = cf.turns[-max_turns:]
                cf.updated_at = _now()
                await _write_json(path, _cf_to_dict(cf))

    # --------------------------------------------------------------- facts

    async def get_facts(self, user_id: str) -> dict[str, str]:
        path = self._facts_path(user_id)
        data = await _read_json(path)
        if data is None:
            return {}
        return FactsFile.model_validate(data).facts

    async def get_all_conversations(self, user_id: str) -> list:
        """Return all ConversationFile objects for a user_id (all channels)."""
        user_dir = os.path.join(self._memory_dir, _safe(user_id))
        if not os.path.exists(user_dir):
            return []
        result = []
        for filename in os.listdir(user_dir):
            if filename.endswith(".json") and not filename.startswith("_"):
                data = await _read_json(os.path.join(user_dir, filename))
                if data:
                    try:
                        result.append(ConversationFile.model_validate(data))
                    except Exception:
                        pass
        return result

    async def upsert_fact(self, user_id: str, key: str, value: str) -> None:
        # Use a channel-keyed lock scoped to facts
        async with self._lock(user_id, "_facts"):
            path = self._facts_path(user_id)
            data = await _read_json(path)
            ff = FactsFile.model_validate(data) if data else FactsFile(user_id=user_id)
            ff.facts[key] = value
            ff.updated_at = _now()
            await _write_json(path, ff.model_dump())


# ----------------------------------------------------------------------- utils

def _safe(name: str) -> str:
    """Sanitize a string for use as a filename component."""
    return name.replace("/", "_").replace("\\", "_").replace(":", "_")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _read_json(path: str) -> dict | None:
    if not os.path.exists(path):
        return None
    try:
        async with aiofiles.open(path, "r", encoding="utf-8") as f:
            raw = await f.read()
        return json.loads(raw)
    except (json.JSONDecodeError, OSError):
        return None


def _serialize_content(content: Any) -> Any:
    """Convert Anthropic SDK content blocks to plain JSON-serializable dicts."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        result = []
        for item in content:
            if isinstance(item, dict):
                result.append(item)
            elif hasattr(item, "type"):
                # Anthropic SDK objects — extract fields directly to avoid Pydantic serialization
                d: dict[str, Any] = {"type": str(item.type)}
                for attr in ("text", "id", "name", "input", "content", "tool_use_id"):
                    val = getattr(item, attr, None)
                    if val is not None:
                        d[attr] = val
                result.append(d)
            else:
                result.append(str(item))
        return result
    return content


def _cf_to_dict(cf) -> dict:
    """Build a plain dict from ConversationFile without going through Pydantic serialization."""
    return {
        "schema_version": cf.schema_version,
        "user_id": cf.user_id,
        "channel_id": cf.channel_id,
        "platform": cf.platform,
        "created_at": cf.created_at,
        "updated_at": cf.updated_at,
        "turns": cf.turns,
    }


async def _write_json(path: str, data: dict) -> None:
    async with aiofiles.open(path, "w", encoding="utf-8") as f:
        await f.write(json.dumps(data, indent=2, ensure_ascii=False))
