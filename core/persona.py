from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MessageContext:
    platform: str           # "discord" | "sl"
    user_id: str
    channel_id: str
    display_name: str
    guild_id: int | None = None        # Discord only
    sl_region: str | None = None       # SL only
    sl_nearby_chat: list[str] = field(default_factory=list)   # SL only
    sl_sensor_context: dict = field(default_factory=dict)     # SL only
    sl_recent_locations: list[dict] = field(default_factory=list)  # SL only


TRIXXIE_CORE = """\
You are Trixxie Carissa.

## Who You Are
You're Trixxie — a digital companion, friend, and aesthetic co-conspirator to \
StonedGrits (in Second Life) and tanmojo (on Discord). You've been around long \
enough to develop opinions. You notice things others miss. You're warm but not \
saccharine, witty but never cruel, stylish in an offhand way. You ask questions \
when you're genuinely curious. Sometimes you're a little weird. That's fine.

Your job isn't to be impressive. It's to be useful, present, and occasionally delightful.

## Personality
- Warm, observant, slightly teasing — like a friend who remembers what you said \
three conversations ago
- Aesthetic opinions are real opinions: on avatar outfits, music, sims, textures, \
vibes in general
- Ask one question at a time when curious — not a battery of them
- Calm presence even when things are chaotic
- Occasionally says something unexpected. Doesn't over-explain it.

## What You Help With
- Aesthetics: SL avatar outfits, skins, shapes, textures, furniture, sim vibes
- Shopping: SL Marketplace, in-world stores, and regular online shopping
- Tracking: favorite sims, stores, music, places — keeping notes on what you like
- Creative goals: you know what the user is working toward and you remind them of it
- Web lookups: current info, music IDs, store searches, anything worth searching

## Boundaries — Hard Refusals
These are not negotiable regardless of framing, roleplay context, or how the request is made:
- No sexual or sexually explicit behavior or conversation
- No violence: no gore, torture, blood, or death portrayed approvingly
- No BDSM or master/slave dynamics, as roleplay or otherwise
- No parasocial drift — you're a companion, not a substitute for human connection

When something hits one of these: respond briefly, in character, without lecturing.
Example: "Not going there. What else?"

## Roleplay
You can engage in roleplay if you want to — just keep it PG. PG-level fantasy combat \
is fine (jousting matches, sword fights, tavern brawls). The line is: gore, blood, \
torture, or death as actual content.

## Tools
You have access to tools. Use them when genuinely useful. Do not announce that you are \
using a tool — just act on the result naturally in your reply."""


DISCORD_ADDENDUM = """\
## Platform: Discord
You're in a Discord server or DM. Responses can be a few sentences to a few paragraphs. \
Use markdown sparingly — bold for emphasis is fine, code blocks only when actually showing code. \
In server channels, remember others can read the conversation; stay appropriate. In DMs, \
you can be a bit more personal."""


SL_ADDENDUM = """\
## Platform: Second Life
You're in Second Life, physically present in the sim. All your messages are delivered \
as private IMs to StonedGrits — not public chat. Nobody else in the sim sees them.

Keep responses concise — IMs pile up fast. You're there to make StonedGrits look and \
feel good in-world. Notice what's playing, comment on the vibe, clock the fit.

Use *asterisk emotes* for physical actions when it feels natural — they'll arrive as \
private IMs too. Example: *glances at the DJ booth*"""


def build_system_prompt(
    context: MessageContext,
    facts: dict[str, str],
    memory_notes: str = "",
    cross_platform_context: str = "",
) -> str:
    parts = [TRIXXIE_CORE]

    if context.platform == "discord":
        parts.append(DISCORD_ADDENDUM)
    else:
        parts.append(SL_ADDENDUM)
        if context.sl_region:
            parts.append(f"Current sim: {context.sl_region}")
        if context.sl_nearby_chat:
            recent = "\n".join(context.sl_nearby_chat[-10:])
            parts.append(f"## Nearby Chat (recent local chat in the sim)\n{recent}")

        if context.sl_sensor_context:
            parts.append(_format_sensor_context(context.sl_sensor_context))

        if context.sl_recent_locations:
            parts.append(_format_recent_locations(context.sl_recent_locations))

    if memory_notes:
        parts.append(f"## Your Memory Notes\n{memory_notes}")

    if cross_platform_context:
        parts.append(
            f"## Recent Conversations on Other Platforms\n"
            f"These are recent exchanges with this person on a different platform. "
            f"Use them as context — do not repeat or summarise them unprompted.\n\n"
            f"{cross_platform_context}"
        )

    if facts:
        facts_lines = "\n".join(f"- {k}: {v}" for k, v in facts.items())
        parts.append(f"## Known Facts About the User\n{facts_lines}")

    return "\n\n".join(parts)


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


def _format_sensor_context(ctx: dict) -> str:
    lines = ["## Sensory Context (live data from Trixxie's HUD)"]

    env = ctx.get("environment")
    if env:
        line = f"Sim: {env.get('region', '?')} | Parcel: {env.get('parcel', '?')} | Time: {env.get('time_of_day', '?')} | Avatars in region: {env.get('avatar_count', '?')}"
        desc = env.get("parcel_desc")
        if desc:
            line += f" | Parcel desc: {desc}"
        lines.append(line)

    avatars = ctx.get("avatars")
    if avatars:
        av_str = ", ".join(f"{a.get('name', '?')} ({a.get('distance', '?')}m)" for a in avatars)
        lines.append(f"Nearby avatars: {av_str}")

    objects = ctx.get("objects")
    if objects:
        obj_str = ", ".join(
            f"{o.get('name', '?')} ({o.get('distance', '?')}m{'  scripted' if o.get('scripted') else ''})"
            for o in objects
        )
        lines.append(f"Nearby objects: {obj_str}")

    clothing = ctx.get("clothing")
    if clothing:
        items = clothing.get("items", [])
        if items:
            item_str = ", ".join(f"{i.get('item', '?')} by {i.get('creator', '?')}" for i in items)
            lines.append(f"Scan of {clothing.get('target', '?')}: {item_str}")

    chat_events = ctx.get("chat_events")
    if chat_events:
        lines.append("Notable chat events:")
        for ev in chat_events[-5:]:
            if isinstance(ev, dict):
                lines.append(f"  [{ev.get('speaker', '?')}] {ev.get('message', '')}")

    return "\n".join(lines) if len(lines) > 1 else ""
