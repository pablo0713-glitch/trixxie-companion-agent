from __future__ import annotations

from typing import Any

from config.settings import Settings
from core.persona import MessageContext
from memory.session_index import SessionIndex


# ------------------------------------------------------------------ schemas

WEB_SEARCH_SCHEMA = {
    "name": "web_search",
    "description": (
        "Search the web for current information, news, facts, shopping links, "
        "sim details, music lookups, or anything where freshness matters. "
        "Returns titles, snippets, and URLs. Do not announce you're searching — "
        "incorporate results naturally."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Targeted search query phrased as a web search, not a question.",
            },
            "num_results": {
                "type": "integer",
                "description": "Number of results to return. Default 5, max 10.",
                "default": 5,
            },
        },
        "required": ["query"],
    },
}

SL_ACTION_SCHEMA = {
    "name": "sl_action",
    "description": (
        "Send a private command to your Second Life presence. "
        "Only available in Second Life — do not call this on Discord. "
        "Actions are queued and executed after your reply is sent. "
        "All output is private IM to the current user — nothing goes to public chat."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "action_type": {
                "type": "string",
                "enum": ["im", "emote", "anim_trigger"],
                "description": (
                    "'im' = send a private instant message. "
                    "'emote' = send *text* as a private IM (seen only by the target avatar). "
                    "'anim_trigger' = play a named animation on your avatar."
                ),
            },
            "text": {
                "type": "string",
                "description": "The text to send, or animation name for anim_trigger. Max 1023 chars.",
            },
            "target_key": {
                "type": "string",
                "description": "Optional avatar UUID. Defaults to the current user.",
            },
        },
        "required": ["action_type", "text"],
    },
}

NOTE_WRITE_SCHEMA = {
    "name": "note_write",
    "description": (
        "Save a persistent note for the current user. Survives across conversations. "
        "Use for places they like, goals, shopping lists, reminders — anything worth keeping. "
        "Overwrites if a note with this title already exists."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Short unique identifier. Examples: 'favorite_sims', 'creative_goals', 'shopping_list'.",
            },
            "content": {"type": "string", "description": "Note content. Plain text, can be multi-line."},
        },
        "required": ["title", "content"],
    },
}

NOTE_READ_SCHEMA = {
    "name": "note_read",
    "description": "Read a previously saved note by title.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Exact title of the note to retrieve."}
        },
        "required": ["title"],
    },
}

NOTE_LIST_SCHEMA = {
    "name": "note_list",
    "description": "List all saved note titles for the current user. Use before note_read if unsure of the exact title.",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}

SESSION_SEARCH_SCHEMA = {
    "name": "session_search",
    "description": (
        "Search your past conversation history for a specific topic, person, place, or event. "
        "Use this when you want to recall something from a previous session that isn't in your "
        "current context. Returns timestamped snippets with platform and date context."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Keywords or phrase to search for in past conversations.",
            },
            "limit": {
                "type": "integer",
                "description": "Max results to return. Default 5, max 10.",
                "default": 5,
            },
        },
        "required": ["query"],
    },
}

MEMORY_SCHEMA = {
    "name": "memory",
    "description": (
        "Curate your persistent memory. Two stores are available:\n"
        "  'memory' — your notes about context, facts, and the world (~2,000 chars).\n"
        "  'user'   — the owner's profile: their preferences, style, background (~1,200 chars).\n"
        "Both are injected into every system prompt. Use this to remember what matters and "
        "forget what doesn't. Do not announce that you are updating memory."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add", "replace", "remove"],
                "description": "'add' appends a new entry. 'replace' rewrites part of an entry. 'remove' deletes an entry.",
            },
            "store": {
                "type": "string",
                "enum": ["memory", "user"],
                "description": "Which memory file to update.",
            },
            "text": {
                "type": "string",
                "description": "Entry text for 'add', or replacement text for 'replace'.",
            },
            "old_text": {
                "type": "string",
                "description": "Substring to match for 'replace' or 'remove'.",
            },
        },
        "required": ["action", "store"],
    },
}


# ------------------------------------------------------------------ registry

class ToolRegistry:
    def __init__(self, settings: Settings, session_index: SessionIndex | None = None) -> None:
        self._settings = settings
        self._session_index = session_index

    def get_definitions(self, context: MessageContext) -> list[dict]:
        from core.persona import get_agent_config
        cfg_tools = get_agent_config().get("tools", {})

        tools = []
        if cfg_tools.get("web_search", True):
            tools.append(WEB_SEARCH_SCHEMA)
        if cfg_tools.get("notes", True):
            tools.extend([NOTE_WRITE_SCHEMA, NOTE_READ_SCHEMA, NOTE_LIST_SCHEMA])
        if context.platform == "sl" and cfg_tools.get("sl_action", True):
            tools.append(SL_ACTION_SCHEMA)
        tools.append(MEMORY_SCHEMA)
        if self._session_index is not None:
            tools.append(SESSION_SEARCH_SCHEMA)
        return tools

    async def dispatch(
        self,
        name: str,
        tool_input: dict[str, Any],
        context: MessageContext,
        action_queue: list[dict],
    ) -> str:
        from core.tool_handlers import notes, sl_action, web_search
        from core.tool_handlers.memory import handle_memory
        from core.tool_handlers.session_search import handle_session_search
        if name == "web_search":
            return await web_search.handle_web_search(
                tool_input,
                context,
                self._settings.search_provider,
                self._settings.search_api_key,
            )
        elif name == "sl_action":
            return await sl_action.handle_sl_action(tool_input, context, action_queue)
        elif name == "note_write":
            return await notes.handle_note_write(tool_input, context, self._settings.notes_dir)
        elif name == "note_read":
            return await notes.handle_note_read(tool_input, context, self._settings.notes_dir)
        elif name == "note_list":
            return await notes.handle_note_list(tool_input, context, self._settings.notes_dir)
        elif name == "memory":
            return await handle_memory(tool_input, context, self._settings.memory_dir)
        elif name == "session_search":
            if self._session_index is None:
                return "Session search is not available."
            return await handle_session_search(tool_input, context, self._session_index)
        else:
            return f"Unknown tool: {name}"
