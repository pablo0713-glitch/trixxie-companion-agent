# Trixxie Carissa — Phase 7 Build Summary
**Date:** 2026-04-17

---

## What Was Built

Phase 7 is a collection of SL communication fixes, a new avatar identity layer, and quality-of-life improvements to the debug panel and platform awareness. No major architectural changes — all additions are isolated modules or targeted edits.

---

## SL Local Chat Trigger — Fixes and Redesign

### Owner exclusion removed

The channel 0 `listen` handler had an `id != llGetOwner()` guard that prevented the HUD owner from triggering local chat responses. Removed — all avatars including the owner can now trigger via name mention.

### Delivery mode: public local chat for all

Previously the HUD sent a private IM to the owner and `llSay(0, ...)` to others (Option 2). Simplified to Option 1: **everyone gets `llSay(0, say_chunked)`**. The response is always public local chat, matching natural conversation flow. The reply visually appears from the HUD object (slightly different color vs. avatar speech — a known SL limitation with HUD-worn scripts).

### `reply_lc_http` action processing was silently dropped

The local chat reply handler only processed the `reply` text field — the `actions` array was ignored entirely. Added the same action loop used by the channel 42 handler:
- `"say"` → `say_chunked(text)` (public local chat)
- `"emote"` → wrap in `*asterisks*` then `say_chunked(text)`

---

## `sl_action` `"say"` Type

Added `"say"` as a new `sl_action` action type alongside the existing `"im"`, `"emote"`, and `"anim_trigger"`. Allows the agent to speak an extra line in public local chat beyond the primary reply.

- `core/tools.py` — `"say"` added to the enum in `SL_ACTION_SCHEMA`
- `core/tool_handlers/sl_action.py` — `"say"` added to `VALID_ACTION_TYPES`
- `lsl/companion_bridge.lsl` — `reply_http` handler (`/42` reply flow) now routes `"say"` to `say_chunked(text)`

---

## SL Platform Awareness Rewrite

The old awareness text said "reply via private IM (never public chat)" — this confused the agent into using `sl_action: "im"` as its primary reply mechanism.

Replaced with a full delivery-mode reference:

| Trigger path | Primary reply delivery |
|---|---|
| Channel 0 name-trigger | `llSay(0)` — public local chat |
| Channel 42 (`/42`) | `llInstantMessage` — private IM |
| Direct IM (Lua) | `SendIM` — private IM |

`sl_action` is documented as **extra** actions beyond the primary reply — not a delivery mechanism for the reply itself.

Added to Style section: **text emoticons only** (`:)`, `:D`, `;)`, etc.) — graphical emoji are not supported in SL. Applied to both `sl` and `opensim` platform awareness defaults in `core/persona.py` and `data/agent_config.json`.

---

## AvatarStore — SL Avatar Identity Registry

**Problem:** The agent had no persistent knowledge of who it had spoken with in SL. When asked on Discord to recall a SL avatar's name, the agent could not.

**Solution:** `memory/avatar_store.py` — a global JSON registry at `data/memory/known_avatars.json`.

### Schema

```json
{
  "schema_version": 1,
  "updated_at": "ISO8601",
  "avatars": {
    "sl_<uuid>": {
      "display_name": "Resident Name",
      "first_seen":   "ISO8601",
      "last_seen":    "ISO8601",
      "channels":     ["local chat", "IM / /42"]
    }
  }
}
```

### Write path

`/sl/message` calls `await avatar_store.record_encounter(sl_user_id, payload.display_name, payload.channel)` on every inbound message — before building `MessageContext`. Channel mapping: `0` → `"local chat"`, anything else → `"IM / /42"`.

### Read path / Block 1 injection

`get_avatar_async(sl_user_id)` is called immediately after `record_encounter`. The result is set on `MessageContext.sl_known_avatar`. `build_system_prompt_blocks()` injects it into Block 1 (dynamic, not cached) via `_format_known_avatar()`:

```
## This Conversation's Avatar
Display name: StonedGrits Resident
Channels seen: IM / /42, local chat
First seen: 2026-04-10 · Last seen: 2026-04-17
```

### Debug panel — display name in user list

`_last_exchange` in `core/agent.py` now stores `display_name`. The `/debug/prompts` endpoint exposes it. The user list JS renders the display name as the primary label with the UUID below it.

### Files changed

| File | Change |
|---|---|
| `memory/avatar_store.py` | New — `AvatarStore` with `record_encounter`, `get_avatar_async`, `get_all` |
| `core/persona.py` | `sl_known_avatar: dict | None` added to `MessageContext`; `_format_known_avatar()` formatter; Block 1 injection |
| `interfaces/sl_bridge/server.py` | `create_sl_app` accepts `avatar_store`; records encounter and sets `context.sl_known_avatar` |
| `main.py` | Instantiates `AvatarStore(settings.memory_dir)`; passes to `create_sl_app` |
| `core/agent.py` | `display_name` added to `_last_exchange` |
| `interfaces/debug_server.py` | `display_name` in `/debug/prompts` response; user list shows name above UUID |

---

## Multi-Alias Trigger Names

**Problem:** Only one trigger name (`TRIGGER_NAME`) was supported in the LSL script.

**Solution:** `TRIGGER_NAME` (string) replaced with `TRIGGER_NAMES` (list). New helper function `is_triggered(string msg)` iterates the list and checks each name as a case-insensitive substring match.

```lsl
list TRIGGER_NAMES = ["Trixxie", "Trix"]; // add aliases freely
```

The trigger check in the channel 0 `listen` handler now calls `is_triggered(message)`. No change to Python.

---

## Emoji Stripping in SL Reply Formatter

**Problem:** Claude occasionally outputs emoji (characters in the U+10000+ range — 4-byte UTF-8). LSL cannot handle non-BMP characters; the first byte (`0xF0`) was rendered as `ð` in local chat.

**Fix:** `cap_reply()` in `interfaces/sl_bridge/formatters.py` now filters out all characters with `ord(c) > 0xFFFF` after the existing Unicode normalization step. Applied to all SL and OpenSim replies. Combined with the platform awareness note ("text emoticons only"), this prevents the problem from both directions.

---

## Debug Panel — `parseMemorySections` Fix

**Problem:** The JS function `parseMemorySections` used a regex with the `gm` flags. In multiline mode, `$` matches the end of every line — not just the end of the string. The lazy `[\s\S]*?` stopped after the first newline, rendering only the first 61 chars of a 1990-char memory block.

**Fix:** Replaced the regex with a line-by-line parser. Iterates lines, detects `MEMORY` / `USER` headers by prefix, accumulates body lines, then splits on `§`. No regex involved in the body parse. Applied in [interfaces/debug_server.py](interfaces/debug_server.py).

---

## `.gitignore` Additions

`data/agent_config.json` and `data/identity/` added to `.gitignore`. These files contain persona text and platform awareness that is personal to a specific instance. They should not be committed to the shared repo — new users get starter content from the wizard defaults instead.

---

## Files Changed

| File | Change |
|---|---|
| `lsl/companion_bridge.lsl` | Owner exclusion removed; `TRIGGER_NAME` → `TRIGGER_NAMES` list + `is_triggered()`; `reply_lc_http` action loop added; `"say"` action type in `/42` reply handler |
| `core/tools.py` | `"say"` added to `sl_action` enum |
| `core/tool_handlers/sl_action.py` | `"say"` added to `VALID_ACTION_TYPES` |
| `data/agent_config.json` | SL platform awareness rewritten (delivery modes, text emoticons only) |
| `core/persona.py` | SL + OpenSim defaults: text emoticons note added; `sl_known_avatar` field; `_format_known_avatar()`; Block 1 injection |
| `memory/avatar_store.py` | New |
| `interfaces/sl_bridge/server.py` | `avatar_store` param; `record_encounter` + `get_avatar_async` on each message |
| `interfaces/sl_bridge/formatters.py` | Non-BMP character strip (emoji → dropped) |
| `interfaces/debug_server.py` | `parseMemorySections` line-by-line parser; `display_name` in endpoint + user list |
| `core/agent.py` | `display_name` in `_last_exchange` |
| `main.py` | `AvatarStore` instantiation + wiring |
| `.gitignore` | `data/agent_config.json`, `data/identity/` added |
