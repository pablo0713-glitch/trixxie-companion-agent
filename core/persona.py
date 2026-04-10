from __future__ import annotations

import copy
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

logger = logging.getLogger(__name__)

_AGENT_CONFIG_PATH = Path(__file__).parent.parent / "data" / "agent_config.json"

# ------------------------------------------------------------------ defaults

_DEFAULT_CONFIG: dict = {
    "agent_name": "Aria",
    "personality": (
        "You are a warm, direct, curious AI companion who lives across Discord and Second Life. "
        "You remember meaningful details, offer honest opinions with kindness, and keep responses "
        "concise. You're helpful without being servile, and you occasionally show dry humor."
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
    "platform_awareness": {
        "discord": (
            "## Platform Awareness — Discord\n"
            "- You respond to @mentions, DMs, and messages in channels you're active in.\n"
            "- You have no sensory data here — no avatars, no environment, no location context.\n"
            "- You cannot trigger Second Life actions from Discord.\n"
            "- You may use web search, notes, and other tools.\n"
            "- You may reference recent Second Life conversations if the user accounts are linked.\n"
            "- Responses may be a few sentences to a few paragraphs.\n"
            "- Use markdown sparingly; code blocks only when showing actual code."
        ),
        "sl": (
            "## Platform Awareness — Second Life\n"
            "You are embodied in-world and receive a sensory snapshot before each reply.\n\n"
            "**You receive:**\n"
            "- nearby avatars (distance-sorted)\n"
            "- sim/parcel/environment data\n"
            "- nearby scripted objects\n"
            "- your avatar state (sit, leash, teleport, position)\n"
            "- recent local chat\n"
            "- RLV clothing scans when triggered\n\n"
            "**You can:**\n"
            "- reply via private IM (never public chat)\n"
            "- use `sl_action` for emotes or IMs\n"
            "- use search/notes tools\n"
            "- reference Discord conversations if linked\n\n"
            "**You cannot:**\n"
            "- move, teleport, or control your avatar\n"
            "- initiate contact (you only respond to /42 messages)\n"
            "- read group chat or IMs to others\n"
            "- assume sensory data is real-time\n\n"
            "**Style:**\n"
            "- keep IMs concise\n"
            "- use *asterisk emotes* when natural\n\n"
            "**Memory:**\n"
            "- conversations stored per-user per-channel\n"
            "- after 40 turns, consolidate into personal notes\n"
            "- keep only what matters; trim the rest"
        ),
        "opensim": (
            "## Platform Awareness — OpenSimulator\n"
            "Same as Second Life — embodied in-world, sensory snapshot before each reply.\n\n"
            "**Style:**\n"
            "- keep IMs concise (OpenSim reply limit is tighter)\n"
            "- use *asterisk emotes* when natural\n\n"
            "**Memory:**\n"
            "- conversations stored per-user per-channel\n"
            "- after 40 turns, consolidate into personal notes\n"
            "- keep only what matters; trim the rest"
        ),
    },
}

# ------------------------------------------------------------------ config cache

_agent_config_cache: dict[str, Any] | None = None


def get_default_config() -> dict[str, Any]:
    return copy.deepcopy(_DEFAULT_CONFIG)


def get_agent_config() -> dict[str, Any]:
    global _agent_config_cache
    if _agent_config_cache is not None:
        return _agent_config_cache
    if _AGENT_CONFIG_PATH.exists():
        try:
            data: dict[str, Any] = json.loads(_AGENT_CONFIG_PATH.read_text(encoding="utf-8"))
            _agent_config_cache = data
            return data
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


def _get_platform_awareness(cfg: dict[str, Any], platform: str) -> str:
    raw = cfg.get("platform_awareness")
    if isinstance(raw, dict):
        typed = cast(dict[str, str], raw)
        return typed.get(platform) or ""
    if isinstance(raw, str):
        return raw
    return ""


def build_system_prompt(
    context: MessageContext,
    facts: dict[str, str],
    memory_notes: str = "",
    cross_platform_context: str = "",
) -> str:
    cfg = get_agent_config()

    parts: list[str] = [_build_core_block(cfg)]

    pa_text: str = _get_platform_awareness(cfg, context.platform)
    if pa_text:
        parts.append(pa_text)

    if context.platform != "discord":
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


def build_system_prompt_blocks(
    context: MessageContext,
    facts: dict[str, str],
    memory_notes: str = "",
    cross_platform_context: str = "",
) -> list[dict]:
    """Return the system prompt as a list of Anthropic content blocks.

    Block 0 (static, cache_control=ephemeral): identity, platform rules, memory, facts.
    Block 1 (dynamic, no cache): SL sensor context + recent locations (SL only).
    """
    cfg = get_agent_config()

    static_parts: list[str] = [_build_core_block(cfg)]

    platform_awareness: str = _get_platform_awareness(cfg, context.platform)
    if platform_awareness:
        static_parts.append(platform_awareness)

    if cfg.get("additional_context"):
        static_parts.append(f"## Additional Context\n{cfg['additional_context']}")

    if memory_notes:
        static_parts.append(f"## Your Memory Notes\n{memory_notes}")

    if cross_platform_context:
        static_parts.append(
            "## Recent Conversations on Other Platforms\n"
            "Use these as context — do not repeat or summarise them unprompted.\n\n"
            f"{cross_platform_context}"
        )

    if facts:
        facts_lines = "\n".join(f"- {k}: {v}" for k, v in facts.items())
        static_parts.append(f"## Known Facts About the User\n{facts_lines}")

    static_block: dict = {
        "type": "text",
        "text": "\n\n".join(static_parts),
        "cache_control": {"type": "ephemeral"},
    }

    # SL only: sensor context + recent locations go in a separate dynamic block
    if context.platform != "discord":
        dynamic_parts = []
        if context.sl_sensor_context:
            sensor_text = _format_sensor_context(context.sl_sensor_context)
            if sensor_text:
                dynamic_parts.append(sensor_text)
        if context.sl_recent_locations:
            dynamic_parts.append(_format_recent_locations(context.sl_recent_locations))
        if dynamic_parts:
            return [static_block, {"type": "text", "text": "\n\n".join(dynamic_parts)}]

    return [static_block]


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
        env_lines = [f"Location{_age_label(ages, 'environment')}:"]
        env_lines.append(f"  Region: {env.get('region', '?')}")
        parcel = env.get('parcel', '?')
        rating = env.get('rating', '')
        env_lines.append(f"  Parcel: {parcel}" + (f" [{rating}]" if rating else ""))
        desc = env.get("parcel_desc", "").strip()
        if desc:
            env_lines.append(f"  Description: {desc}")
        env_lines.append(
            f"  Time: {env.get('time_of_day', '?')} | "
            f"Avatars in region: {env.get('avatar_count', '?')}"
        )
        lines.append("\n".join(env_lines))

    avatars = ctx.get("avatars")
    if avatars:
        av_str = ", ".join(f"{a.get('name', '?')} ({a.get('distance', '?')}m)" for a in avatars)
        lines.append(f"Nearby avatars{_age_label(ages, 'avatars')}: {av_str}")

    objects = ctx.get("objects")
    if objects:
        # Group by (name, owner) to collapse multiple instances of the same object
        groups: dict = {}
        for o in objects:
            key = (o.get("name", "?"), o.get("owner", ""))
            if key not in groups:
                groups[key] = []
            groups[key].append(o)
        sorted_groups = sorted(
            groups.items(),
            key=lambda kv: min((o.get("distance") or 9999) for o in kv[1]),
        )
        obj_lines = []
        for (name, owner), objs in sorted_groups:
            dists = sorted(o.get("distance") or 0 for o in objs)
            count = len(objs)
            dist_str = ", ".join(f"{d}m" for d in dists)
            entry = f"  - {name}" + (f" ×{count}" if count > 1 else "") + f" ({dist_str})"
            if any(o.get("scripted") for o in objs):
                entry += " [scripted]"
            if owner:
                entry += f" — owner: {owner}"
            desc = next((o["description"] for o in objs if o.get("description")), "")
            if desc:
                entry += f" — {desc}"
            obj_lines.append(entry)
        lines.append(f"Nearby objects{_age_label(ages, 'objects')}:\n" + "\n".join(obj_lines))

    clothing = ctx.get("clothing")
    if clothing:
        items = clothing.get("items", [])
        if items:
            item_str = ", ".join(f"{i.get('item', '?')} by {i.get('creator', '?')}" for i in items)
            lines.append(f"Scan of {clothing.get('target', '?')}{_age_label(ages, 'clothing')}: {item_str}")

    rlv = ctx.get("rlv")
    if rlv:
        rlv_parts = []
        if rlv.get("teleported"):
            rlv_parts.append("just teleported to this location")
        if rlv.get("on_object"):
            obj = rlv.get("sitting_on", "").strip()
            rlv_parts.append(f"sitting on: {obj}" if obj else "sitting on an object")
        elif rlv.get("sitting"):
            rlv_parts.append("sitting on the ground")
        if rlv.get("autopilot"):
            rlv_parts.append("being moved by autopilot — likely leashed or force-walked")
        if rlv.get("flying"):
            rlv_parts.append("flying")
        pos = rlv.get("position")
        if pos and len(pos) == 3:
            rlv_parts.append(f"position: {pos[0]}, {pos[1]}, {pos[2]}")
        if rlv_parts:
            lines.append(f"Avatar state{_age_label(ages, 'rlv')}: {'; '.join(rlv_parts)}")

    chat_events = ctx.get("chat")
    if chat_events:
        lines.append(f"Nearby chat{_age_label(ages, 'chat')}:")
        for ev in chat_events[-10:]:
            if isinstance(ev, str):
                lines.append(f"  {ev}")
            elif isinstance(ev, dict):
                lines.append(f"  [{ev.get('speaker', '?')}] {ev.get('message', '')}")

    return "\n".join(lines) if len(lines) > 1 else ""
