# Trixxie Carissa — Phase 8 Build Summary
**Date:** 2026-04-18

---

## What Was Built

Phase 8 focuses on conversational memory quality, avatar identity recall, avatar mute/unmute, a voice hook, and LSL HUD reliability fixes. No major architectural changes — all additions are targeted modules or edits to existing layers.

---

## Mute / Unmute — `sl_action` Types

Added `mute_avatar` and `unmute_avatar` as new `sl_action` action types, routing to Cool VL Viewer's `AddMute` / `RemoveMute` Lua API.

### Python side

- `core/tools.py` — `"mute_avatar"` and `"unmute_avatar"` added to `SL_ACTION_SCHEMA` enum; `required` changed to `["action_type"]` (text is optional for mute types); `target_key` description updated.
- `core/tool_handlers/sl_action.py` — `VALID_ACTION_TYPES` extended; `is_mute_type` branch: requires `target_key`, strips `sl_` prefix if present, queues `{action_type, target_key}`, returns feedback string.

### Lua side

- `lua/trixxie_companion.lua` — `OnHTTPReply` action loop: `mute_avatar` calls `AddMute(target_key, 1)`; `unmute_avatar` calls `RemoveMute(target_key, 1)`.

---

## Session Search — Cross-User Recall Fix

**Problem:** `SessionIndex.search()` had `AND s.user_id = ?` in the FTS SQL, scoping results to the current speaker only. The agent could not recall conversations with other avatars.

**Fix:** Removed the `user_id` filter entirely. All of Trixxie's conversation history is now searchable — `session_search` is the agent's memory, not a per-user silo.

- `memory/session_index.py` — `_SEARCH_SQL` no longer filters by `user_id`; `search()` signature changed to `(self, query, limit)`.
- `core/tool_handlers/session_search.py` — removed `user_id` param from `search()` call; result formatting updated to show `display_name` when available.
- `core/persona.py` — conversation integrity rule updated: "ALWAYS call `session_search` BEFORE claiming you don't recall a person or event."

---

## Display Name in Session Index

**Problem:** Only the UUID was stored in `sessions.db` — the agent could not find conversations by avatar display name when searching.

**Solution:** Added a `display_name` column to the `sessions` table and `sessions_fts` virtual table. FTS5 searches both columns by default.

### Changes

- `memory/session_index.py`:
  - `display_name TEXT NOT NULL DEFAULT ''` added to schema
  - `sessions_fts` updated: `fts5(content, display_name, content=sessions, content_rowid=id)`
  - `_MIGRATE_STMTS` runs `ALTER TABLE` + `DROP TABLE sessions_fts` + `CREATE VIRTUAL TABLE` on existing DBs
  - `index_turn()` now accepts and stores `display_name`
  - `backfill_display_names(avatar_map)` method populates historical records from `known_avatars.json`
  - `query()` method added for structured SQL access (see below)

- `memory/base.py` — `display_name: str = ""` added to abstract `append_turn()` signature
- `memory/file_store.py` — `display_name` threaded through `append_turn()` → `index_turn()`
- `core/agent.py` — passes `context.display_name` when indexing the user turn
- `main.py` — calls `session_index.backfill_display_names(avatar_map)` at startup using `known_avatars.json` data

---

## `session_query` Tool — Structured History Access

New tool for structured SQL-style queries over conversation history. Complementary to `session_search` (FTS keyword search) — useful for "who have I spoken with?" style questions.

### Schema

| Parameter | Type | Description |
|---|---|---|
| `mode` | `"speakers" \| "turns"` | Return one row per person vs. individual messages |
| `date_from` | string | Start date filter, YYYY-MM-DD |
| `date_to` | string | End date filter, YYYY-MM-DD |
| `platform` | `"sl" \| "discord"` | Filter to one platform |
| `include_names` | list[string] | Only return these display names |
| `exclude_names` | list[string] | Exclude these display names |
| `limit` | integer | Max results (default 20, max 50) |

**Speakers mode** — one row per unique person: name, platform, turn count, date range.
**Turns mode** — individual messages: timestamp, name, platform, content snippet.

### Files

- `core/tools.py` — `SESSION_QUERY_SCHEMA` added; registered in `get_definitions()` and `dispatch()`
- `core/tool_handlers/session_query.py` — new handler; calls `SessionIndex.query()` with all filters
- `memory/session_index.py` — `query()` method: two SQL paths (speakers / turns) with optional WHERE clauses for date, platform, names

---

## Voice Hook — `/sl/voice` Stub

Simplest possible voice integration point. No audio processing — the endpoint is a well-defined stub that can be activated when a voice-capable model is configured.

### Server side

- `interfaces/sl_bridge/server.py` — `SLVoicePayload` Pydantic model; `POST /sl/voice` endpoint: auth-checked, config-guarded, returns a stub message if `tools.voice` is `false` in agent config.
- `core/persona.py` — `"voice": False` added to default tools config; `**Voice:**` section added to SL platform awareness default.
- `data/agent_config.json` — `"voice": false` in tools; voice capability text in SL awareness.

### Wizard

- `setup/wizard.js` — `voice_enabled` state; Voice tool card in Step 5 (SL-only toggle); review badge; save to `agent_config.json`.

### HUD

- `lsl/companion_bridge.lsl` — `integer s_voice = FALSE` toggle; Voice button in `show_menu()` dialog; `show_status()` output; menu handler.

---

## LSL HUD — Startup Scan Fix

**Problem:** `state_entry()` only called `do_env_scan()`. When the HUD started in a script-enabled area, avatar and object sensor data was missing until the first timer ticks fired.

**Fix:** Added `do_avatar_scan()`, `do_rlv_scan()`, and `do_object_scan()` to `state_entry()`. The server now has a full sensor snapshot immediately after the HUD attaches.

---

## LSL HUD — `AGENT_IN_VOICE` Error Fix

The stride-3 avatar scan list `[dist, key, name]` was introduced to support per-avatar voice detection via `AGENT_IN_VOICE`. This constant does not exist in standard LSL (not in the `llGetAgentInfo` bitmask set). The compiler rejected it.

**Fix:** Removed the `in_voice` field from the avatar JSON payload. The stride-3 list was retained (no regression). The `s_voice` toggle is now documented as a server-side endpoint guard only — not an avatar-level detection mechanism.

---

## TRIGGER_NAMES — "Trixx" Alias Added

`TRIGGER_NAMES` in `lsl/companion_bridge.lsl` updated from `["Trixxie", "Trix"]` to `["Trixxie", "Trix", "Trixx"]` at the owner's request.

---

## Documentation — Architecture Consolidation

`lsl/ARCHITECTURE.md` merged into root `ARCHITECTURE.md`. A new **"LSL HUD — Detailed Reference"** section covers API endpoints, sensor data formats, timer schedule, scan mode state machine, HTTP key management, chat buffer, function reference, and OpenSimulator compatibility. `lsl/ARCHITECTURE.md` deleted. `README.md` project layout updated.

---

## Mute/Unmute — Full Debugging and Fix (second session, 2026-04-18)

The mute feature was wired in phase 7 but had no visible effect. A full debugging cycle identified and fixed three separate root causes.

### Root cause 1 — Wrong argument type for `AddMute`

Per the Cool VL Viewer Lua manual (page 14), `AddMute(name_or_id, type)` with `type=1` ("avatar by Id") requires a **UUID**, not a display name. An earlier change had switched from UUID to display name — this was incorrect. The call always failed silently because Cool VL discards mute requests with the wrong argument shape.

**Fix:** `lua/trixxie_companion.lua` — mute/unmute/is_muted handlers now use `action["target_key"]` (UUID) with `ctx.origin_id` as fallback. Display name (`action["text"]`) is used only for the feedback IM.

### Root cause 2 — Agent had no UUID to pass

The agent could see the current conversation partner's display name but not their UUID. For third-party mutes ("mute SashaSativa"), the only UUID source was the avatar radar — but the radar payload only included `name` and `distance`. The agent had no way to look up SashaSativa's UUID.

**Fixes:**
- `lsl/companion_bridge.lsl` — avatar scan JSON now includes `"key": "<uuid>"` for each nearby avatar
- `core/persona.py` — `_format_sensor_context()` renders the UUID inline: `Name (12.3m) [UUID: ...]`
- `interfaces/sl_bridge/server.py` — `sl_uuid` (raw UUID, `sl_` prefix stripped) injected into `known_avatar` dict before passing to `MessageContext`
- `core/persona.py` — `_format_known_avatar()` now shows `SL UUID: <uuid>` in Block 1
- `core/tools.py` — `target_key` field description updated: UUID required for mute types, not display name
- `data/agent_config.json` — mute/unmute/is_muted descriptions updated to reference `target_key` (UUID from nearby avatars list)

### Root cause 3 — Cool VL Viewer `DecodeJSON` unwraps single-element arrays

`OnHTTPReply` printed `"processing 0 actions"` even when the Python server confirmed the actions list was non-empty. Raw reply logging revealed the JSON was arriving correctly (`"actions":[{...}]`), but Cool VL Viewer's `DecodeJSON` implementation **unwraps single-element JSON arrays into the object itself** — `[{"action_type":"mute_avatar",...}]` became `{"action_type":"mute_avatar",...}`. `ipairs()` then iterated the object's keys (`action_type`, `target_key`, `text`), not the intended action.

**Fix:** `lua/trixxie_companion.lua` — `OnHTTPReply` now normalizes `raw_actions` into `action_list` before iterating:
- If `raw_actions["action_type"] ~= nil` → single object was unwrapped → wrap in `{raw_actions}`
- Otherwise → iterate numerically (0-based then 1-based) to handle multi-action arrays

### Additional: `is_muted` action type

Added `is_muted` as a new `sl_action` type (read-only query). The agent calls it with `target_key` (UUID); Lua calls `IsMuted(uuid, 1)` and sends the result back as an IM. Platform awareness clarifies that `is_muted` is a query, not a toggle — the agent must not assume calling it changes mute state.

### Debug tooling added and cleaned up

- `interfaces/sl_bridge/server.py` — action log promoted from `DEBUG` to `INFO` level to always appear in the server console
- `lua/trixxie_companion.lua` — `print()` debug traces added throughout the action loop during diagnosis (retained for ongoing troubleshooting)

---

## Files Changed

| File | Change |
|---|---|
| `core/tools.py` | `mute_avatar`/`unmute_avatar`/`is_muted` in schema; `target_key` described as UUID; `SESSION_QUERY_SCHEMA` added |
| `core/tool_handlers/sl_action.py` | Mute/unmute/is_muted action types |
| `core/tool_handlers/session_query.py` | New — `session_query` handler |
| `core/tool_handlers/session_search.py` | Removed `user_id` filter; `display_name` in output |
| `core/persona.py` | Conversation integrity rule; voice awareness; UUID in known avatar block; UUID in avatar radar display |
| `core/agent.py` | `display_name` passed to `append_turn()` |
| `memory/session_index.py` | `display_name` column; FTS migration; `backfill_display_names()`; `query()` |
| `memory/base.py` | `display_name` in abstract `append_turn()` |
| `memory/file_store.py` | `display_name` threaded through; `_sanitize_tool_pairs()` for orphaned tool_result fix |
| `interfaces/sl_bridge/server.py` | `SLVoicePayload`; `POST /sl/voice` stub; `sl_uuid` injected into known_avatar; action log at INFO |
| `setup/wizard.js` | Voice tool card in Step 5 |
| `lua/trixxie_companion.lua` | Mute/unmute/is_muted routing; `DecodeJSON` single-element array normalization; UUID for `AddMute`/`RemoveMute`/`IsMuted`; debug traces |
| `lsl/companion_bridge.lsl` | Startup scans; `s_voice` toggle + menu; `TRIGGER_NAMES` + "Trixx"; `AGENT_IN_VOICE` removed; `"key"` field in avatar JSON |
| `data/agent_config.json` | `"voice": false`; voice awareness; mute descriptions updated to reference UUID + `target_key` |
| `main.py` | Startup `backfill_display_names()` |
| `ARCHITECTURE.md` | LSL HUD internals merged in; avatar sensor format updated with `key`; mute action table updated; is_muted documented |
| `lsl/ARCHITECTURE.md` | Deleted — content merged into root ARCHITECTURE.md |
| `README.md` | `session_query.py` added; `lsl/ARCHITECTURE.md` removed; TRIGGER_NAMES default updated |
