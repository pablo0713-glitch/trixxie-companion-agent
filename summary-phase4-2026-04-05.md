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
