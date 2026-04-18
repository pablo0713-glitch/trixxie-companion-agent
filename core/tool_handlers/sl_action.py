from __future__ import annotations

from core.persona import MessageContext

VALID_ACTION_TYPES = {"say", "im", "emote", "anim_trigger", "mute_avatar", "unmute_avatar"}


async def handle_sl_action(
    tool_input: dict,
    context: MessageContext,
    action_queue: list[dict],
) -> str:
    """Queue a Second Life action. Returns a confirmation string for Claude's context."""
    if context.platform != "sl":
        return "sl_action is only available in Second Life."

    action_type = tool_input.get("action_type", "").lower()
    text = tool_input.get("text", "").strip()
    target_key = tool_input.get("target_key", "")

    if action_type not in VALID_ACTION_TYPES:
        return f"Unknown action type '{action_type}'. Valid types: {', '.join(sorted(VALID_ACTION_TYPES))}"

    is_mute_type = action_type in ("mute_avatar", "unmute_avatar")

    if not text and not is_mute_type:
        return "No text provided for action."

    if is_mute_type:
        if not target_key:
            return f"{action_type} requires target_key (avatar UUID)."
        if target_key.startswith("sl_"):
            target_key = target_key[3:]
        label = text or target_key
        action_queue.append({"action_type": action_type, "target_key": target_key})
        verb = "Muted" if action_type == "mute_avatar" else "Unmuted"
        return f"{verb} {label}"

    # Trim to SL limits
    if len(text) > 1023:
        text = text[:1020] + "..."

    action: dict = {"action_type": action_type, "text": text}
    if target_key:
        action["target_key"] = target_key

    action_queue.append(action)
    return f"Queued {action_type}: {text[:60]}{'...' if len(text) > 60 else ''}"
