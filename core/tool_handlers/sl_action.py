from __future__ import annotations

from core.persona import MessageContext

VALID_ACTION_TYPES = {"say", "im", "emote", "anim_trigger", "mute_avatar", "unmute_avatar", "is_muted"}

_MUTE_VERBS = {"mute_avatar": "Muted", "unmute_avatar": "Unmuted", "is_muted": "Checking mute status for"}


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

    is_mute_type = action_type in _MUTE_VERBS

    if not text and not is_mute_type:
        return "No text provided for action."

    if is_mute_type:
        display_name = text  # preferred: display name passed via text field
        if target_key.startswith("sl_"):
            target_key = target_key[3:]
        if not display_name and not target_key:
            return f"{action_type} requires the avatar's display name (text field) or target_key (UUID)."
        action: dict = {"action_type": action_type}
        if display_name:
            action["text"] = display_name
        if target_key:
            action["target_key"] = target_key
        action_queue.append(action)
        label = display_name or target_key
        verb = _MUTE_VERBS[action_type]
        return f"{verb} {label}"

    # Trim to SL limits
    if len(text) > 1023:
        text = text[:1020] + "..."

    action = {"action_type": action_type, "text": text}
    if target_key:
        action["target_key"] = target_key

    action_queue.append(action)
    return f"Queued {action_type}: {text[:60]}{'...' if len(text) > 60 else ''}"
