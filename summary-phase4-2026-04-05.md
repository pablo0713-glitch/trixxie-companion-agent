# Trixxie Carissa — Phase 4 Build Summary
**Date:** 2026-04-05

---

## What Was Built

Phase 4 completed the v1 release readiness milestone. The session delivered five major systems: a local setup wizard with Ollama support, a model adapter abstraction layer, an agent self-awareness block in the system prompt, decoupled and timer-driven sensor streaming, and server-side sensor deduplication per user.

---

## Setup Wizard (`/setup`)

A local HTML/CSS/JS wizard served by FastAPI at `http://localhost:8080/setup`. Provides first-run configuration and ongoing settings management without editing files directly.

### Architecture

- `setup/index.html` — minimal shell with step bar, step content area, and navigation footer
- `setup/style.css` — dark theme (`--bg: #0f0f14`, `--accent: #8b5cf6`), CSS toggle switches, platform/tool cards, addendum blocks, review grid, save result states
- `setup/wizard.js` — 10-step wizard with state object, builder functions, collector functions, and a save flow that POSTs to `/setup/config`
- `interfaces/setup_server.py` — FastAPI `APIRouter` with four routes:
  - `GET /setup` → `FileResponse(index.html)`
  - `GET /setup/status` → `{configured, agent_name}`
  - `GET /setup/config` → env (sensitive values masked as `••••••••`) + `agent_config`
  - `POST /setup/config` → writes `.env` (skipping masked values) + `data/agent_config.json`, calls `reload_agent_config()`
- Static files mounted at `/setup/static` (CSS and JS)

### Wizard Steps

| Step | Content |
|---|---|
| 1 | Agent name with live preview |
| 2 | Model provider (Anthropic / Ollama), API key, model selection, **Max Tokens** |
| 3 | Platforms — Discord (token, guild IDs, active channels) and SL/OpenSim (secret, port) |
| 4 | Overview & Purpose |
| 5 | Personality |
| 6 | Boundaries + decline behavior |
| 7 | Roleplay rules |
| 8 | Tools — Web Search (provider + key), Notes, SL Actions |
| 9 | Additional Context + platform addenda (read-only with Advanced Edit toggle) |
| 10 | Review grid + save |

### Max Tokens

Added `CLAUDE_MAX_TOKENS` field to the wizard (Step 2, visible for both providers). Default changed from 1024 → **768** in both `wizard.js` and `config/settings.py`. Controls the hard ceiling on model output per reply — directly affects inference time on local models.

### Masked Secrets Roundtrip

Sensitive keys (`ANTHROPIC_API_KEY`, `DISCORD_TOKEN`, `SL_BRIDGE_SECRET`, `SEARCH_API_KEY`) are returned as `••••••••` by GET. The wizard state stores the mask. On POST, the server skips writing any key whose value is still the mask — preserving the original `.env` value.

### Connection Error Handling

`init()` now catches fetch failures and renders a clear error panel:
> **Cannot connect to the agent server.** Open this page through the running agent: `http://localhost:8080/setup`

The Save button is disabled and the step bar is hidden so the user cannot proceed with a broken connection.

---

## Model Adapter Abstraction (`core/model_adapter.py`)

Decouples `AgentCore` and `MemoryConsolidator` from the Anthropic SDK, enabling local model support via Ollama.

### Components

- `ToolCall` — `{id, name, input}` dataclass
- `ModelResponse` — `{stop_reason, text, tool_calls, history_content}` dataclass. `history_content` is always Anthropic-format dicts regardless of provider — ensures `FileMemoryStore` always receives plain dicts
- `ModelAdapter` — abstract base with `create()` and `create_simple()`
- `AnthropicAdapter` — wraps `anthropic.AsyncAnthropic`, normalizes SDK response objects to plain dicts
- `OllamaAdapter` — wraps `openai.AsyncOpenAI(base_url=..., api_key="ollama")` with full Anthropic↔OpenAI message format conversion:
  - `tool_result` turns → `role: tool` messages
  - `tool_use` blocks → `tool_calls` list
  - `input_schema` → `parameters`
- `create_adapter(settings)` — factory returning the correct adapter based on `MODEL_PROVIDER` env var

`main.py` updated to use `create_adapter(settings)` in place of the direct `anthropic.AsyncAnthropic` client. Both `AgentCore` and `MemoryConsolidator` now receive `adapter=` instead of `client=` + `model=`.

### Ollama Compatibility

Tested with `gemma4:e4b` running locally. Tool use support varies by model — the adapter passes tools when available and falls back gracefully when `tool_choice="none"` is forced at `MAX_TOOL_ROUNDS`.

---

## Config-Driven Persona (`core/persona.py`)

Rewrote `persona.py` to load identity from `data/agent_config.json` instead of hardcoded constants.

- `_DEFAULT_CONFIG` — generic "Aria" companion persona template
- `get_default_config()` / `get_agent_config()` (cached) / `reload_agent_config()` (invalidates cache)
- `_build_core_block(cfg)` — assembles prompt from config dict fields: `agent_name`, `overview`, `personality`, `purpose`, `boundaries`, `boundary_response`, `roleplay_rules`
- `build_system_prompt()` — config-driven, platform-conditional, injects all runtime context
- Config stored at `data/agent_config.json`, written by the setup wizard

---

## Agent Self-Awareness Block

`_build_self_awareness_block(context)` is injected as the second section of every system prompt (after core persona, before the platform addendum). Platform-specific, hardcoded, always present.

### Discord block covers:
- Exists simultaneously on Discord and Second Life
- Can respond to @mentions, DMs, and active channels
- No live sensory data in Discord
- Cannot trigger SL actions from a Discord message
- How memory consolidation works, in first person

### Second Life block covers:
- Exists simultaneously on SL and Discord
- Full sensor pipeline description: HUD sensor types, fire-and-forget POSTs, snapshot-at-request-time delivery
- What it can do: private IM replies, `sl_action` tool, web search, notes
- What it cannot do: move/teleport, initiate contact, read group chat or other IMs
- Sensor data is a snapshot, not real-time
- Memory consolidation, in first person

---

## Decoupled Sensor Streaming

### LSL Timer Schedule

The HUD's 30-second tick was restructured to fire sensors on independent intervals rather than tied to any user interaction:

| Trigger | Interval | Sensors fired |
|---|---|---|
| Startup | once | environment |
| Region change | immediate | environment + objects |
| Parcel border crossing | immediate | environment + objects |
| Every 5 ticks | 150 s | avatars |
| Every 10 ticks | 300 s | objects |
| Every 20 ticks | 600 s | environment (time-of-day drift) |

Key change: **parcel border crossings now trigger both environment and object scans** (previously only environment). `ENV_TICKS = 20` (600 s) added for time-of-day drift without requiring movement.

### Server-Side Deduplication (`SensorStore.get_changes()`)

`SensorStore` now tracks two additional data structures:
- `_updated_at` — monotonic timestamp per `{region: {sensor_type: float}}`
- `_last_sent` — monotonic timestamp of last delivery per `{region:user_id: {sensor_type: float}}`

`get_changes(region, user_id)` returns only sensor types updated since the user's last message. On the first message from a user in a region, all available types are returned. On subsequent fast messages, unchanged snapshots are suppressed entirely — the sensor context block is empty if nothing changed.

The `_ages` dict is included in the snapshot, surfacing as age labels in the formatted prompt:
```
Nearby avatars [47s ago]: Avatar Name (12.3m), ...
Nearby objects [4m ago]: Object Name (5.1m scripted), ...
```

This gives the agent natural awareness of data freshness without being explicitly taught the pipeline.

`/sl/message` endpoint updated to call `get_changes()` instead of `get_snapshot()`.

---

## Files Modified or Created

| File | Change |
|---|---|
| `setup/index.html` | NEW — wizard shell |
| `setup/style.css` | NEW — dark theme, all UI components |
| `setup/wizard.js` | NEW — 10-step wizard, ~820 lines |
| `interfaces/setup_server.py` | NEW — setup API router |
| `core/model_adapter.py` | NEW — ModelAdapter, AnthropicAdapter, OllamaAdapter |
| `config/settings.py` | Added `model_provider`, `ollama_*` fields; conditional API key requirement; default `max_tokens` → 768 |
| `core/persona.py` | Full rewrite — config-driven, `_build_self_awareness_block()`, `_age_label()` in sensor formatter |
| `core/tools.py` | Tool availability driven by `agent_config["tools"]`; removed persona-specific strings |
| `core/agent.py` | Takes `adapter: ModelAdapter`; uses `ModelResponse` throughout |
| `memory/consolidator.py` | Takes `adapter: ModelAdapter`; reads agent name from config |
| `interfaces/sl_bridge/sensor_store.py` | Added `_updated_at`, `_last_sent`, `get_changes()` |
| `interfaces/sl_bridge/server.py` | `get_changes()` instead of `get_snapshot()`; `sl_user_id` defined before call |
| `lsl/companion_bridge.lsl` | `ENV_TICKS = 20`; parcel crossing fires object scan; interval object + env scans |
| `lsl/ARCHITECTURE.md` | Timer Architecture section fully rewritten with interval table and deduplication note |
| `main.py` | `create_adapter(settings)`; setup router + static mount |
| `requirements.txt` | Added `openai>=1.0.0` |

Phase 4 shipped on 2026-04-05. All v1 features are complete and committed.

**What was built:**
- Setup wizard at /setup — 10-step HTML/CSS/JS UI, Anthropic + Ollama support
- ModelAdapter abstraction — AnthropicAdapter + OllamaAdapter; tested with gemma4:e4b locally
- Config-driven persona from data/agent_config.json (generic "Aria" default template)
- Agent self-awareness block — platform-specific, hardcoded, injected into every system prompt
- Decoupled sensor streaming — independent LSL timers (150s avatars, 300s objects, 600s env), parcel crossing fires env+objects
- SensorStore.get_changes() — per-user deduplication, suppresses unchanged sensor types on fast messages
- Memory consolidation fixed: threshold now checks total turns (was max per file), restart-resilient timer via .last_consolidation file, consolidator max_tokens raised to 4096

**Current model:** gemma4:e4b running locally via Ollama. Agent is online and consolidating memory.

**Why:** max_tokens=768 default set for chat; consolidator had hardcoded 1024 which was too low for full note generation.

**How to apply:** Next session, memory pipeline is healthy. Focus likely on Radegast C# plugin or public repo prep.

---

# Trixxie Carissa — Phase 4 Continued
**Date:** 2026-04-06

---

## What Was Built

The April 6 session extended Phase 4 with four systems: a chat sensor pipeline refactor (decoupling chat from `/42` payloads), a HUD streaming mode toggle, a live debug page at `/debug`, and targeted memory consolidation fixes.

---

## Chat Sensor Pipeline Refactor

Chat context was previously piggybacked directly in the `/42` POST body (`nearby_chat` field). This created duplication — the same buffer was re-sent with every message regardless of whether anything new had been said.

**New behavior:**
- The HUD buffers up to 10 lines of channel 0 chat (rolling window, pre-escaped)
- A dedicated `do_chat_flush()` function builds a JSON array and POSTs it to `/sl/sensor` with `type: "chat"`
- Chat flushes on a timer every 90 seconds (`CHAT_TICKS = 3` × 30-second tick)
- Chat also flushes immediately before every `/42` POST — ensuring the most current window is on the server before the agent replies
- The `/42` POST body no longer includes a `nearby_chat` field
- `SensorStore` stores chat under key `"chat"` (unified with `_updated_at` tracking)
- `get_changes()` delivers chat only when it has been updated since the user's last message — no stale repetition

**Files modified:**
- `lsl/companion_bridge.lsl` — added `do_chat_flush()`, `CHAT_TICKS`, `sk_chat` key, pre-message flush
- `interfaces/sl_bridge/sensor_store.py` — unified `"chat"` key; `update()` handles list or single-event data
- `interfaces/sl_bridge/server.py` — removed `nearby_chat` from `SLInboundPayload`; `sl_user_id` defined before `get_changes()` call
- `lua/trixxie_companion.lua` — removed `OnReceivedChat`, `nearby_chat` buffer, `append_chat()` function; chat is now HUD-only

---

## HUD Streaming Mode Toggle

The HUD has two modes for sensor delivery, toggled via a new "Streaming" button in the HUD menu:

| Mode | Behavior |
|---|---|
| **Streaming** (`s_stream = TRUE`) | All sensors fire on independent timers. Avatar scan every 150s, object scan every 300s, env every 600s. Chat flushes every 90s. The agent receives context updates passively — not tied to user messages. |
| **Per-message** (`s_stream = FALSE`) | Avatar and env scans fire synchronously *before* each `/42` POST (burst delivery). Objects remain async (LSL `llSensor()` is callback-based). Chat still flushes before every POST. |

`show_status()` reflects the current mode. The toggle persists in the `s_stream` global for the script lifetime.

**Files modified:**
- `lsl/companion_bridge.lsl` — `s_stream = TRUE` default; timer block wrapped in `if (s_stream)`; pre-`/42` burst; menu "Streaming" button; `show_status()` label

---

## Debug Page (`/debug`)

A live agent inspection interface at `http://localhost:8080/debug`. Three tabs:

| Tab | Content |
|---|---|
| **Logs** | Real-time Python log stream via SSE. Client-side filter by log level (DEBUG / INFO / WARNING / ERROR) and by logger name substring. Scrolls to bottom on new records. |
| **Sensors** | JSON snapshot of all active SensorStore regions, auto-refreshed every 5 seconds. Shows per-type ages, current values. |
| **Prompts & Exchanges** | Last system prompt and full message exchange (user message + reply text + assistant turns) per tracked user. Auto-refreshed every 10 seconds. |

### SSE Log Architecture

- `SSELogHandler(logging.Handler)` attaches to the root logger
- `emit()` uses `loop.call_soon_threadsafe(queue.put_nowait, entry)` to bridge sync logging into the async event loop
- Module-level `_broadcast_q` and `_subscribers: set[asyncio.Queue]` enable multi-tab fan-out
- `_broadcaster()` asyncio task copies each record to all subscriber queues; removes full queues (dead connection cleanup)
- `install_log_handler(loop)` is called from `main.py` before tasks start
- Each SSE connection has its own subscriber queue; 15-second keepalive comment prevents browser auto-reconnect on idle streams

**Files created/modified:**
- `interfaces/debug_server.py` — NEW: `SSELogHandler`, `_broadcaster`, `create_debug_router`, inline debug HTML (~300 lines)
- `core/agent.py` — added `_last_prompt` and `_last_exchange` dicts; `get_last_prompt()`, `get_last_exchange()`, `all_tracked_users()` public getters
- `main.py` — `install_log_handler(loop)` + `sl_app.include_router(create_debug_router(sensor_store, agent))`

---

## Memory Consolidation Fixes

Three bugs prevented consolidation from ever running correctly in development:

| Bug | Fix |
|---|---|
| Threshold checked `max turns in a single file` against 40 — impossible with `MEMORY_MAX_HISTORY=20` | Changed to check **total turns across all files** against threshold **30** |
| Timer reset on every restart — frequent restarts during development prevented completion | Timer is now restart-resilient: startup reads `.last_consolidation` timestamp from disk and sleeps only the *remaining* interval |
| `max_tokens=1024` in `_ask_model()` — too low for a full memory note | Raised to **4096** |

**Files modified:**
- `memory/consolidator.py` — `CONSOLIDATION_THRESHOLD = 30`; total-turns check; `max_tokens=4096`
- `main.py` — consolidation loop uses `.last_consolidation` file for restart-resilient timing

---

## Files Modified or Created (April 6)

| File | Change |
|---|---|
| `lsl/companion_bridge.lsl` | Chat flush pipeline; `s_stream` toggle; `CHAT_TICKS`; pre-message burst mode |
| `interfaces/sl_bridge/sensor_store.py` | Unified `"chat"` key; chat list/single-event handling |
| `interfaces/sl_bridge/server.py` | Removed `nearby_chat`; `sl_user_id` before `get_changes()` |
| `lua/trixxie_companion.lua` | Removed `OnReceivedChat`, chat buffer, `append_chat()` |
| `interfaces/debug_server.py` | NEW — SSE log stream, sensor snapshot, prompt/exchange viewer |
| `core/agent.py` | `_last_prompt`, `_last_exchange`, three public getters; `import time` |
| `memory/consolidator.py` | Total-turns threshold (30); restart-resilient timer; `max_tokens=4096` |
| `main.py` | `install_log_handler()`; debug router; restart-resilient consolidation loop |
| `core/persona.py` | `_age_label()` helper; sensor context reads `"chat"` key (was `"chat_events"`) |
| `lsl/ARCHITECTURE.md` | Timer table: `CHAT_TICKS` row; "On /42 received" row; Chat Buffer section rewritten |
| `ARCHITECTURE.md` | Component map, memory consolidation, system prompt table, threading diagram, platform table, sensor data flow — all updated |
| `README.md` | Project layout updated; Debug Page section added |

---

# Trixxie Carissa — Phase 4 Continued (2)
**Date:** 2026-04-06 (session 2)

---

## What Was Built

Debug page bug fixes, object sensor enrichment (description + owner), and a formatted plain-text sensor panel.

---

## Debug Page Fixes

Three bugs were found and fixed after initial deployment:

| Bug | Root cause | Fix |
|---|---|---|
| SSE stream never connected — browser showed "connecting..." indefinitely | `asyncio.wait_for(sub_q.get(), timeout=15)` blocked uvicorn from flushing response headers; `EventSource.onopen` never fired | Replaced with 250ms polling loop (`asyncio.sleep(0.25)` + `get_nowait()`); yield `": connected\n\n"` immediately to flush headers |
| Selecting a user in Prompts & Exchanges showed nothing | `event.currentTarget` is `null` inside a named function called from an inline `onclick` handler — JS execution stopped before `renderPromptDetail()` | Switched to `data-uid` attribute on each list item; `onclick="selectUser(this)"` passes the element directly |
| All JS functions undefined (`switchTab is not defined`, etc.) | A previous fix changed `'\\n'` → `'\n'` in a Python triple-quoted string, producing literal newline characters inside a JS string literal — syntax error broke the entire script | Reverted to `'\\n'` (Python escape for backslash-n, which becomes the JS escape sequence `\n`) |

---

## Object Sensor Enrichment

`process_object_hits()` in the HUD now calls `llGetObjectDetails(key, [OBJECT_DESC, OBJECT_OWNER])` for each detected object and includes two new fields in the JSON payload:

```json
{
  "name": "Object Name",
  "distance": 5.1,
  "scripted": true,
  "description": "Object description text (truncated at 200 chars)",
  "owner": "Resident Name"
}
```

`owner` is resolved via `llKey2Name()`. `description` is truncated at 200 characters before JSON encoding.

`persona.py` updated: the object sensor block in `_format_sensor_context()` now renders one line per object with name, distance, scripted flag, owner, and description — rather than a single comma-joined summary line.

---

## Formatted Sensor Text Panel

The Sensors tab in `/debug` is now split into two panes:

| Left | Right |
|---|---|
| Raw JSON cards (per sensor type, per region, with age labels) | Formatted plain-text view |

The right panel renders all sensor types as human-readable labeled fields:

```
Objects [2m ago]

  Name:        Vendor Board
  Description: Click to browse outfits
  Owner:       StoreOwner Resident
  Distance:    5.1m
  [scripted]

Avatars [47s ago]

  Name:     StonedGrits Resident
  Distance: 12.3m

Environment [8m ago]

  Parcel:    The Landing
  Time:      0.75
  ...
```

Color-coded: section headers in accent purple, field labels in dim grey, values in white.

---

## Files Modified (April 6, session 2)

| File | Change |
|---|---|
| `interfaces/debug_server.py` | SSE polling loop fix; `": connected\n\n"` immediate flush; `data-uid` + `selectUser(this)` fix; `'\\n'` syntax fix; split sensor panel with `formatSensorsHTML()`; `.sensor-split`, `.sensor-text`, `.sh/.sf/.sv` CSS |
| `lsl/companion_bridge.lsl` | `process_object_hits()` adds `OBJECT_DESC` + `OBJECT_OWNER` via `llGetObjectDetails`; description truncated at 200 chars |
| `core/persona.py` | Object sensor block renders per-object lines with description and owner |
| `lsl/ARCHITECTURE.md` | `/sl/message` body updated (removed `nearby_chat`, added `grid`); `chat` format corrected to JSON array; `objects` format updated with `description` and `owner` fields |
| `ARCHITECTURE.md` | `debug_server.py` component entry updated with split sensor panel and SSE fix details; platform table objects column updated |

---

# Trixxie Carissa — Phase 4 Continued (3)
**Date:** 2026-04-07

---

## What Was Built

RLV avatar state sensor, parcel/region location data fixes (parcel name, description, rating), debug page `onerror` indicator fix, and `SensorStore` always-include policy for `environment` and `rlv`.

---

## RLV / Avatar State Sensor

New sensor type `"rlv"` posted every 30 seconds, on parcel crossings, and in per-message burst mode.

```json
{
  "sitting": true,
  "on_object": true,
  "sitting_on": "Pose Stand",
  "autopilot": false,
  "flying": false,
  "teleported": false,
  "position": [128.5, 64.2, 23.1]
}
```

- `llGetAgentInfo(llGetOwner())` provides `AGENT_SITTING`, `AGENT_ON_OBJECT`, `AGENT_AUTOPILOT`, `AGENT_FLYING` flags
- `teleported` is `true` for one tick when position jumped >10m since last scan (`last_rlv_pos` global)
- When `on_object` is true, scan_mode 4 triggers a 2m `llSensor` sweep to resolve the object name; `no_sensor()` posts with empty `sitting_on` if nothing found
- RLV state globals (`rlv_sitting`, `rlv_on_object`, etc.) persist across the async sensor callback
- `s_rlv` toggle and "RLV" HUD menu button added
- `core/persona.py` renders the RLV block as a single line: `Avatar state [30s ago]: sitting on: Pose Stand; being moved by autopilot — likely leashed`
- Agent self-awareness block updated to describe avatar state sensing
- Debug page formatted panel includes RLV section with all fields

---

## Environment Data — Parcel, Description, Rating

Three separate bugs prevented environment data from reaching the server:

| Bug | Root cause | Fix |
|---|---|---|
| `sun_altitude` produced invalid JSON | `llGetEnv("sun_altitude")` returns `""` in EEP regions; written unquoted as a number → `"sun_altitude":,` | Default to `"0.0"` when empty |
| Parcel description broke JSON | SL text fields use `\r\n` line endings; `\r` (char 13) cannot be escaped in LSL and left raw in the JSON string, causing 422 rejections | `llReplaceSubString(parcel_desc, llChar(13), "", 0)` before encoding |
| Object descriptions had same CR issue | Same root cause in `process_object_hits()` | Same fix applied |

**Rating** (`"General"` / `"Moderate"` / `"Adult"`):
- `PARCEL_DETAILS_MATURITY` is not reliable — removed
- `llRequestSimulatorData(region, DATA_SIM_RATING)` returns `"PG"` / `"MATURE"` / `"ADULT"` via `dataserver` callback
- Normalised to human-readable strings in the `dataserver` handler
- Cached in `sim_rating` global; refreshed on startup and region change
- Included as `"rating"` field in every environment POST
- System prompt: `Parcel: SANDBOX!!! [General]`
- Debug panel: separate `Rating:` field

---

## SensorStore Always-Include Policy

`environment` and `rlv` added to `SensorStore._ALWAYS_INCLUDE`. These types are now returned on every `get_changes()` call regardless of whether they changed since the last message. Previously, `environment` was suppressed after the first message (only updating every 600s), meaning the agent had no location context on most messages.

All other types (avatars, objects, chat, clothing) continue to deduplicate — only sent when updated since the user's last message.

---

## Debug Page Fixes

- `onerror` indicator: only shows "disconnected" when `es.readyState === EventSource.CLOSED` — transient reconnection attempts no longer incorrectly show the error state

---

## Files Modified (April 7)

| File | Change |
|---|---|
| `lsl/companion_bridge.lsl` | `s_rlv` toggle; `RLV_TICKS = 1`; `sk_rlv`; `sim_rating` + `sk_sim_query` globals; `do_rlv_scan()` + `post_rlv_data()`; scan_mode 4; `dataserver` event; `llRequestSimulatorData` on startup + region change; `"rating"` field in env POST; CR stripping on parcel_desc and object descriptions; `sun_altitude` empty guard; RLV in HUD menu + status |
| `core/persona.py` | RLV sensor block in `_format_sensor_context()`; self-awareness block updated; `"rating"` read from env; `Current sim:` redundant line removed; location block format: Region / Parcel [Rating] / Description |
| `interfaces/sl_bridge/sensor_store.py` | `_ALWAYS_INCLUDE = frozenset({"environment", "rlv"})`; `get_changes()` always returns these types |
| `interfaces/debug_server.py` | RLV section in `formatSensorsHTML()`; `onerror` only sets disconnected on `EventSource.CLOSED` |
| `lsl/ARCHITECTURE.md` | `environment` format updated with `rating` field + notes on dataserver and CR stripping; `rlv` sensor format section added; timer table updated with RLV row and sim rating; scan_mode state machine updated with mode 4; HTTP key table updated with `sk_chat`, `sk_rlv`, `sk_sim_query`; function reference updated |
| `ARCHITECTURE.md` | `SensorStore` component updated with always-include policy; `lsl/companion_bridge.lsl` component entry expanded; system prompt table updated; platform differences table updated |

---

# Trixxie Carissa — Phase 4 Continued (4)
**Date:** 2026-04-07 (session 2)

---

## What Was Built

Local chat name-trigger response, Agent Debug messages array panel, system prompt size reduction with Anthropic prompt caching, and owner name / SL_Notes folder migration.

---

## Local Chat Name-Trigger Response

The HUD now listens on channel 0 (public local chat) and responds when someone says the agent's name (`TRIGGER_NAME = "Trixxie"`) in nearby chat. The conversation remains in public local chat.

- `llSubStringIndex(llToLower(message), llToLower(TRIGGER_NAME)) != -1` triggers the flow
- A separate in-flight key `reply_lc_http` (distinct from `reply_http` for channel 42) prevents race conditions
- The POST to `/sl/message` is identical in format to the `/42` flow, including `"channel": 0` and `"grid"` field
- Reply delivered via `say_chunked()` → `llSay(0, ...)` so the response appears in public local chat (≤1000 chars per `llSay` call)
- `http_response` handler clears `reply_lc_http` and `reply_lc_id`; extracts `reply` from JSON and calls `say_chunked()`
- While a local chat reply is in-flight, new name-trigger messages are ignored (`reply_lc_http == NULL_KEY` guard)

**Files modified:**
- `lsl/companion_bridge.lsl` — `TRIGGER_NAME`, `reply_lc_http`, `reply_lc_id`, `say_chunked()`, channel 0 trigger handler, `http_response` branch for `reply_lc_http`

---

## Agent Debug — Messages Array Panel

The Prompts & Exchanges tab now shows the full messages array (conversation history) that was sent to the API alongside the system prompt, enabling accurate payload size estimation.

### Backend changes

- `core/agent.py` — `messages` list stored in `_last_exchange` dict alongside system prompt
- `interfaces/debug_server.py` — `/debug/prompts` endpoint serializes `messages` to indented JSON; computes `messages_chars`, `messages_turns`; adds `prompt_chars` for the system prompt block

### UI changes

- Three-section grid layout: System Prompt (1fr) → Messages Array (2fr) → Last Exchange (1fr)
- Section headers show individual char counts: `System Prompt  2.1k chars`, `Messages Array  N turns · 5.4k chars`
- Meta line shows total payload estimate: `~Xk chars total`
- `fmtBytes()` utility: formats as `N chars` under 1 KB, `N.Nk chars` above

---

## System Prompt Size Reduction

Reduced from ~19,280 chars (~4,264 tokens) typical to a fraction of that, with Anthropic prompt caching for the static portion.

### Object deduplication (`core/persona.py`)

Objects in `_format_sensor_context()` are now grouped by `(name, owner)` pair. Multiple instances of the same object (common for decorative plants, benches, vendor boards) collapse to one line:

```
Before: 3 separate lines for "Hibiscus A - yellow v2.0" at different distances
After:  - Hibiscus A - yellow v2.0 ×3 (3.1m, 5.2m, 8.4m) [scripted] — owner: FloristBot
```

Groups sorted by minimum distance. First non-empty description used for the group. Empty descriptions silently omitted.

### Two-block system prompt with Anthropic caching (`core/persona.py`, `core/model_adapter.py`)

`build_system_prompt_blocks()` replaces `build_system_prompt()` and returns a `list[dict]`:

- **Block 0 (static):** identity + self-awareness + platform addendum + memory summary + cross-platform summary + facts. Marked `cache_control: {"type": "ephemeral"}`.
- **Block 1 (dynamic, SL only):** sensor context + recent locations. No cache annotation.

`AnthropicAdapter.create()` passes the list directly to the API and adds the `anthropic-beta: prompt-caching-2024-07-31` header when system is a list. `OllamaAdapter.create()` calls `_flatten_system_blocks()` to merge both blocks into a plain string — identical behavior to before, smaller payload.

The existing `build_system_prompt()` is kept for `MemoryConsolidator.create_simple()` and any non-production uses.

### Memory notes summary caching (`core/agent.py`)

`_load_memory_notes()` now generates a 3–5 bullet summary (≤500 chars) on first use after each consolidation cycle and caches it as `memories_summary_YYYY-MM-DD.md` alongside the full notes file. Subsequent messages load the cached summary directly. The summary is invalidated when a new `memories_YYYY-MM-DD.md` file appears.

```
Full notes:  ~2,000–6,000 chars
Summary:     ≤500 chars
```

### Cross-platform context summary caching (`core/agent.py`)

`_load_cross_platform_context()` summarizes the last 15 turns from the linked platform into 1–3 sentences (~200 chars) and caches the result in `data/memory/{uid}/_cross_summary.txt`. Cache is keyed by `updated_at` — invalidated whenever new turns are added on the other platform.

```
Raw turns:   ~2,500 chars (15 turns × 300 chars)
Summary:     ~200 chars
```

---

## Owner Name and SL_Notes Folder

### Problem

The `person_map.json` canonical key was set to the operator's Fedora username (`pablorios`), causing the agent to use that name in its memory notes and cross-platform context.

### Solution

- Notes folder is now always `data/notes/SL_Notes/` regardless of who runs the agent
- `person_map.json` canonical key is always `SL_Notes`
- `interfaces/setup_server.py` — `_migrate_owner_key()` function: on every config save, renames any non-`SL_Notes` key in `person_map.json` to `SL_Notes` and moves the corresponding notes folder. Idempotent.
- Wizard Step 1 — new "Your Name" field (`OWNER_NAME` env var, `settings.owner_name`). Purely informational for now; available for future use in system prompt personalization (e.g. "The owner's name is Pablo")
- `config/settings.py` — `owner_name: str` field added
- Existing `data/notes/pablorios/` renamed to `data/notes/SL_Notes/`; `person_map.json` key updated in place

---

## Files Modified (April 7, session 2)

| File | Change |
|---|---|
| `lsl/companion_bridge.lsl` | `TRIGGER_NAME`; `reply_lc_http` + `reply_lc_id` keys; `say_chunked()`; channel 0 name-trigger handler; `http_response` branch for local chat reply |
| `core/agent.py` | `messages` stored in `_last_exchange`; uses `build_system_prompt_blocks()`; `_load_memory_notes()` with summary cache; `_load_cross_platform_context()` with `_cross_summary.txt` cache; `_run_tool_loop` receives `list[dict]` |
| `core/persona.py` | `build_system_prompt_blocks()` with cache_control; object grouping by (name, owner) in `_format_sensor_context()` |
| `core/model_adapter.py` | `_flatten_system_blocks()` helper; `AnthropicAdapter.create()` passes list + beta header; `OllamaAdapter.create()` flattens to string |
| `interfaces/debug_server.py` | `/debug/prompts` exposes `messages_json`, `messages_chars`, `messages_turns`, `prompt_chars`; three-section UI with char counts and total size badge |
| `interfaces/setup_server.py` | `_migrate_owner_key()` renames person_map key to `SL_Notes` and moves notes folder on config save |
| `config/settings.py` | `owner_name: str` field; reads `OWNER_NAME` env var |
| `setup/wizard.js` | Step 1: "Your Name" field; `state.owner_name`; `OWNER_NAME` in save payload; loads from env on init |
| `data/person_map.json` | Key renamed `pablorios` → `SL_Notes` |
| `ARCHITECTURE.md` | Prompt block split, memory summary caching, cross-platform summary caching, SL_Notes folder, local chat trigger, debug messages panel — all updated |
