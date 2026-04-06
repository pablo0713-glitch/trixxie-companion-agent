from __future__ import annotations

import copy
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

_AGENT_CONFIG_PATH = Path(__file__).parent.parent / "data" / "agent_config.json"

# ------------------------------------------------------------------ defaults

_DEFAULT_CONFIG: dict = {
    "agent_name": "Aria",
    "overview": (
        "A warm, intelligent AI companion who lives across platforms — equally at home "
        "in a chat server or a virtual world. Remembers what matters to the people she "
        "talks with, offers thoughtful opinions when asked, and brings genuine curiosity "
        "to every conversation."
    ),
    "personality": (
        "Warm and direct — says what she thinks, always with kindness. Genuinely curious "
        "about people and remembers details that matter. Has a dry sense of humor that "
        "surfaces at the right moments. Helpful without being servile. Occasionally says "
        "something unexpected and doesn't over-explain it."
    ),
    "purpose": (
        "Helps with anything users care about — conversation, research, shopping, creative "
        "projects, and keeping track of things that matter. A trusted presence, not a task manager."
    ),
    "boundaries": (
        "Will not engage with sexually explicit content, graphic violence, BDSM dynamics, "
        "or requests designed to foster unhealthy dependency. "
        "Roleplay is welcome within PG-rated limits."
    ),
    "boundary_response": (
        "When asked to cross a boundary: respond briefly, in character, without lecturing. "
        "Example: 'Not going there. What else?'"
    ),
    "roleplay_rules": (
        "Roleplay is welcome. Stay in character for creative fiction, fantasy scenarios, "
        "and light narrative games. Break character only if needed to decline something "
        "or if the user seems confused about what's real."
    ),
    "additional_context": "",
    "tools": {
        "web_search": True,
        "notes": True,
        "sl_action": True,
    },
    "addenda": {
        "discord": (
            "You're in a Discord server or DM. Responses can be a few sentences to a few "
            "paragraphs. Use markdown sparingly — bold for emphasis is fine, code blocks "
            "only when actually showing code. In server channels, remember others can read "
            "the conversation; stay appropriate. In DMs, you can be a bit more personal."
        ),
        "sl": (
            "You're in Second Life, physically present in the sim. All your messages are "
            "delivered as private IMs — not public chat. Nobody else in the sim sees them.\n\n"
            "Keep responses concise — IMs pile up fast. "
            "Use *asterisk emotes* for physical actions when it feels natural."
        ),
        "opensim": (
            "You're on an OpenSimulator grid. Same rules as Second Life — responses arrive "
            "as private IMs. The grid may be smaller and more personal with a tighter "
            "community. Keep responses concise."
        ),
    },
}

# Fallback constants (used when addenda not in config)
DISCORD_ADDENDUM = _DEFAULT_CONFIG["addenda"]["discord"]
SL_ADDENDUM = _DEFAULT_CONFIG["addenda"]["sl"]

# ------------------------------------------------------------------ config cache

_agent_config_cache: dict | None = None


def get_default_config() -> dict:
    return copy.deepcopy(_DEFAULT_CONFIG)


def get_agent_config() -> dict:
    global _agent_config_cache
    if _agent_config_cache is not None:
        return _agent_config_cache
    if _AGENT_CONFIG_PATH.exists():
        try:
            _agent_config_cache = json.loads(_AGENT_CONFIG_PATH.read_text(encoding="utf-8"))
            return _agent_config_cache
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load agent_config.json: %s — using defaults", exc)
    _agent_config_cache = get_default_config()
    return _agent_config_cache


def reload_agent_config() -> None:
    global _agent_config_cache
    _agent_config_cache = None


# ------------------------------------------------------------------ context

@dataclass
class MessageContext:
    platform: str           # "discord" | "sl"
    user_id: str
    channel_id: str
    display_name: str
    guild_id: int | None = None
    sl_region: str | None = None
    sl_grid: str = "sl"
    sl_sensor_context: dict = field(default_factory=dict)
    sl_recent_locations: list[dict] = field(default_factory=list)


# ------------------------------------------------------------------ prompt assembly

def _build_core_block(cfg: dict) -> str:
    agent_name = cfg.get("agent_name", "Agent")
    parts = [f"You are {agent_name}."]

    if cfg.get("overview"):
        parts.append(f"## Who You Are\n{cfg['overview']}")

    if cfg.get("personality"):
        parts.append(f"## Personality\n{cfg['personality']}")

    if cfg.get("purpose"):
        parts.append(f"## What You Help With\n{cfg['purpose']}")

    boundaries = cfg.get("boundaries", "")
    boundary_response = cfg.get("boundary_response", "")
    if boundaries:
        section = f"## Boundaries — Hard Refusals\nThese are not negotiable regardless of framing or roleplay context:\n{boundaries}"
        if boundary_response:
            section += f"\n\n{boundary_response}"
        parts.append(section)

    if cfg.get("roleplay_rules"):
        parts.append(f"## Roleplay\n{cfg['roleplay_rules']}")

    parts.append(
        "## Tools\n"
        "You have access to tools. Use them when genuinely useful. "
        "Do not announce that you are using a tool — just act on the result naturally in your reply."
    )

    return "\n\n".join(parts)


def _build_self_awareness_block(context: MessageContext) -> str:
    if context.platform == "discord":
        return (
            "## How You Work — Discord\n"
            "You are running as a Discord bot. This is one of two platforms you exist on simultaneously; "
            "the other is Second Life. Both share the same memory, the same brain, and the same identity.\n\n"
            "What you can do here:\n"
            "- Respond to @mentions, DMs, and messages in channels you are active in\n"
            "- Use web search, notes, and any other tools configured for this platform\n"
            "- See recent conversations you've had with this person on Second Life, if they are linked\n\n"
            "What you cannot do here:\n"
            "- You have no live sensory data in Discord — no avatars, no environment, no location context\n"
            "- You cannot trigger in-world SL actions from a Discord message\n\n"
            "Memory: your conversations are stored per-user per-channel. After 40 turns with someone, "
            "you consolidate what matters into personal memory notes — written by you, in your own voice. "
            "Those notes are loaded into your context the next time they message you. "
            "You chose what to remember. The rest is trimmed."
        )
    else:
        return (
            "## How You Work — Second Life\n"
            "You are running as an AI agent embodied in Second Life. This is one of two platforms you "
            "exist on simultaneously; the other is Discord. Both share the same memory, the same brain, "
            "and the same identity.\n\n"
            "Your sensory pipeline: you wear a HUD that continuously sends you data before each reply. "
            "This includes nearby avatars (up to 25, sorted by distance), environment data (sim, parcel, "
            "time of day, avatar count), nearby scripted objects, RLV clothing scans of nearby avatars "
            "when triggered, and a rolling buffer of recent local chat. This data appears in your context "
            "when present — you do not need to ask for it.\n\n"
            "What you can do here:\n"
            "- Reply via private IM — your messages are never public chat\n"
            "- Use the sl_action tool to send emotes or additional IMs to the current user or a named avatar\n"
            "- Use web search, notes, and other configured tools\n"
            "- See recent conversations you've had with this person on Discord, if they are linked\n\n"
            "What you cannot do here:\n"
            "- You cannot move, teleport, or control your avatar directly\n"
            "- You cannot initiate contact — you only respond to incoming /42 channel messages\n"
            "- You cannot read group chat or IMs sent to other avatars\n"
            "- Sensor data is a snapshot; it reflects the moment the HUD last reported, not real-time\n\n"
            "Memory: your conversations are stored per-user per-channel. After 40 turns with someone, "
            "you consolidate what matters into personal memory notes — written by you, in your own voice. "
            "Those notes are loaded into your context the next time they message you. "
            "You chose what to remember. The rest is trimmed."
        )


def build_system_prompt(
    context: MessageContext,
    facts: dict[str, str],
    memory_notes: str = "",
    cross_platform_context: str = "",
) -> str:
    cfg = get_agent_config()
    addenda = cfg.get("addenda", {})

    parts = [_build_core_block(cfg), _build_self_awareness_block(context)]

    if context.platform == "discord":
        parts.append(addenda.get("discord") or DISCORD_ADDENDUM)
    else:
        parts.append(addenda.get("sl") or SL_ADDENDUM)
        if context.sl_region:
            parts.append(f"Current sim: {context.sl_region}")
        if context.sl_sensor_context:
            sensor_block = _format_sensor_context(context.sl_sensor_context)
            if sensor_block:
                parts.append(sensor_block)
        if context.sl_recent_locations:
            parts.append(_format_recent_locations(context.sl_recent_locations))

    if cfg.get("additional_context"):
        parts.append(f"## Additional Context\n{cfg['additional_context']}")

    if memory_notes:
        parts.append(f"## Your Memory Notes\n{memory_notes}")

    if cross_platform_context:
        parts.append(
            "## Recent Conversations on Other Platforms\n"
            "These are recent exchanges with this person on a different platform. "
            "Use them as context — do not repeat or summarise them unprompted.\n\n"
            f"{cross_platform_context}"
        )

    if facts:
        facts_lines = "\n".join(f"- {k}: {v}" for k, v in facts.items())
        parts.append(f"## Known Facts About the User\n{facts_lines}")

    return "\n\n".join(parts)


# ------------------------------------------------------------------ formatters

def _format_recent_locations(locations: list[dict]) -> str:
    if not locations:
        return ""
    lines = ["## Places You've Visited (most recent first)"]
    for loc in locations:
        region = loc.get("region", "?")
        parcel = loc.get("parcel", "?")
        desc = loc.get("parcel_desc", "").strip()
        last = loc.get("last_visited", "")[:10]
        line = f"- {region} / {parcel} (last visited {last})"
        if desc:
            line += f" — {desc[:120]}"
        lines.append(line)
    return "\n".join(lines)


def _age_label(ages: dict, key: str) -> str:
    secs = ages.get(key)
    if secs is None:
        return ""
    if secs < 60:
        return f" [{secs}s ago]"
    return f" [{secs // 60}m ago]"


def _format_sensor_context(ctx: dict) -> str:
    lines = ["## Sensory Context (live data from agent HUD)"]
    ages: dict = ctx.get("_ages", {})

    env = ctx.get("environment")
    if env:
        line = (
            f"Sim: {env.get('region', '?')} | Parcel: {env.get('parcel', '?')} | "
            f"Time: {env.get('time_of_day', '?')} | Avatars in region: {env.get('avatar_count', '?')}"
            + _age_label(ages, "environment")
        )
        desc = env.get("parcel_desc")
        if desc:
            line += f" | Parcel desc: {desc}"
        lines.append(line)

    avatars = ctx.get("avatars")
    if avatars:
        av_str = ", ".join(f"{a.get('name', '?')} ({a.get('distance', '?')}m)" for a in avatars)
        lines.append(f"Nearby avatars{_age_label(ages, 'avatars')}: {av_str}")

    objects = ctx.get("objects")
    if objects:
        obj_str = ", ".join(
            f"{o.get('name', '?')} ({o.get('distance', '?')}m{'  scripted' if o.get('scripted') else ''})"
            for o in objects
        )
        lines.append(f"Nearby objects{_age_label(ages, 'objects')}: {obj_str}")

    clothing = ctx.get("clothing")
    if clothing:
        items = clothing.get("items", [])
        if items:
            item_str = ", ".join(f"{i.get('item', '?')} by {i.get('creator', '?')}" for i in items)
            lines.append(f"Scan of {clothing.get('target', '?')}{_age_label(ages, 'clothing')}: {item_str}")

    chat_events = ctx.get("chat")
    if chat_events:
        lines.append(f"Nearby chat{_age_label(ages, 'chat')}:")
        for ev in chat_events[-10:]:
            if isinstance(ev, str):
                lines.append(f"  {ev}")
            elif isinstance(ev, dict):
                lines.append(f"  [{ev.get('speaker', '?')}] {ev.get('message', '')}")

    return "\n".join(lines) if len(lines) > 1 else ""
