from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from pydantic import BaseModel, Field


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ConversationFile(BaseModel):
    schema_version: int = 1
    user_id: str
    channel_id: str
    platform: str
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)
    # Each turn is {"role": "user"|"assistant", "content": str | list}
    # list content preserves tool_use / tool_result blocks as-is
    turns: list[dict[str, Any]] = Field(default_factory=list)


class FactsFile(BaseModel):
    schema_version: int = 1
    user_id: str
    updated_at: str = Field(default_factory=_now)
    facts: dict[str, str] = Field(default_factory=dict)
