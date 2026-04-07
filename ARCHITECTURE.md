# Architecture — Trixxie Carissa

## Overview

Trixxie is a stateful AI agent built around a single shared core (`AgentCore`) that serves two platform interfaces simultaneously. The core handles identity, memory, tool use, and the Claude API loop. The interfaces handle platform-specific protocol, formatting, and delivery.

```
┌─────────────────────────────────────────────────────┐
│                      AgentCore                      │
│  system prompt · tool loop · memory · rate limiting │
└──────────────────┬──────────────────┬───────────────┘
                   │                  │
     ┌─────────────▼──────┐  ┌────────▼──────────────┐
     │   Discord Bot       │  │   SL HTTP Bridge       │
     │   (discord.py)      │  │   (FastAPI + uvicorn)  │
     │                     │  │                        │
     │   @mention / DM     │  │   POST /sl/message     │
     │   → AgentCore       │  │   ← JSON reply         │
     │   ← chunked reply   │  │                        │
     └─────────────────────┘  └──────┬──────────┬──────┘
                                     │          │
                          PostHTTP   │          │ llHTTPRequest
                   ┌─────────────────▼──┐  ┌───▼────────────────┐
                   │  Cool VL Viewer     │  │  LSL HUD            │
                   │  automation.lua     │  │  (worn by Trixxie)  │
                   │                     │  │                     │
                   │  private IM → POST  │  │  /42 msg → POST     │
                   │  typing indicator   │  │  sensor data → POST │
                   │  reply → SendIM     │  │  reply → llIM       │
                   └─────────────────────┘  └─────────────────────┘
```

Both interfaces share the same `AgentCore`, `FileMemoryStore`, and `LocationStore`. A `PersonMap` links platform-specific user IDs to a canonical person identity so that conversations on either platform inform the same memory context.

For LSL HUD internals — sensor data formats, timer architecture, scan modes, HTTP key management — see [lsl/ARCHITECTURE.md](lsl/ARCHITECTURE.md).

---

## Component Map

```
main.py                          Entry point. Starts Discord bot, SL HTTP bridge,
                                 and memory consolidation loop concurrently via
                                 asyncio.gather().

config/
  settings.py                    Loads all configuration from environment variables.
                                 Single Settings dataclass passed everywhere.

core/
  agent.py          AgentCore    Central message handler. Loads history + facts,
                                 loads memory notes and cross-platform context,
                                 builds system prompt, runs the Claude tool loop,
                                 persists all turns, returns AgentResponse.
                                 Uses AsyncAnthropic — fully non-blocking.

  persona.py        Persona      Config-driven identity. Loads agent_config.json
                                 (or defaults) via get_agent_config() with
                                 module-level cache. reload_agent_config() invalidates
                                 the cache after wizard saves.
                                 Platform awareness is wizard-editable per platform
                                 (discord / sl / opensim) and injected via
                                 _get_platform_awareness(cfg, platform). Describes what
                                 the agent can perceive, what it cannot do, and how to
                                 behave — no longer hardcoded.
                                 MessageContext carries platform, user, channel,
                                 sensor data, and recent location history.
                                 build_system_prompt_blocks() returns a list of Anthropic
                                 content blocks: Block 0 (static identity + memory,
                                 cache_control=ephemeral) + Block 1 (sensor context,
                                 SL only, no cache). Objects in the sensor block are
                                 grouped by (name, owner) with ×N count and distance
                                 list to collapse repeated decorative objects.

  model_adapter.py  ModelAdapter Abstract adapter over the model client.
                                 AnthropicAdapter wraps AsyncAnthropic; accepts system
                                 as str or list[dict]. When a list is passed, adds the
                                 anthropic-beta: prompt-caching-2024-07-31 header so
                                 the static identity block is eligible for caching.
                                 OllamaAdapter wraps openai.AsyncOpenAI pointed at
                                 the Ollama /v1 endpoint, with full Anthropic↔OpenAI
                                 message format conversion. _flatten_system_blocks()
                                 merges content-block lists to a plain string for Ollama.
                                 ModelResponse.history_content is always Anthropic-
                                 format dicts regardless of provider — FileMemoryStore
                                 always receives plain dicts.

  tools.py          ToolRegistry Holds tool schemas and dispatch logic.
                                 get_definitions(context) filters by platform —
                                 sl_action is only included when platform == "sl".

  rate_limiter.py   RateLimiter  Per-user token bucket. In-memory. Prevents runaway
                                 usage — a polite slowdown, not a hard block.

  tool_handlers/
    web_search.py                Brave or Serper Search API. Returns formatted
                                 title/snippet/URL list to Claude.
    sl_action.py                 Appends to an action_queue list. Actions flush
                                 back to the interface after the loop ends.
    notes.py                     Per-user flat-file note storage. One .txt per note.

memory/
  base.py           AbstractMemoryStore   Interface contract. Async methods:
                                          get_history, append_turn, get_facts,
                                          upsert_fact, get_all_conversations.
                                          Swap implementations here.
  file_store.py     FileMemoryStore       JSON files on disk. Per-(user,channel)
                                          asyncio.Lock prevents write races.
                                          _serialize_content() converts Anthropic SDK
                                          objects to plain dicts via direct attribute
                                          access (avoids Pydantic MockValSer on Py 3.14).
  schemas.py                              Pydantic models for JSON file structure.
  person_map.py     PersonMap             Loads data/person_map.json. Maps canonical
                                          person IDs ↔ platform user IDs.
  consolidator.py   MemoryConsolidator    Background task. Summarises conversations
                                          into first-person notes via Claude.
                                          Runs every 6 hours.
  location_store.py LocationStore         Persists SL region/parcel visit history.
                                          Per-user asyncio.Lock. Deduplicates by
                                          region+parcel key.

data/
  person_map.json                         Canonical identity → platform ID list.
  memory/{safe_user_id}/
    {channel_id}.json                     Conversation turns per channel.
    _facts.json                           Persistent key/value facts about the user.
    locations.json                        SL visit history (LocationStore).
  notes/SL_Notes/
    memories_YYYY-MM-DD.md                Consolidated memory notes written by Claude.
    memories_summary_YYYY-MM-DD.md        Compact 3–5 bullet summary (≤500 chars),
                                          generated on first use after each consolidation
                                          and cached to disk. Regenerated on next
                                          consolidation. Passed to the agent instead of
                                          the full notes file.

interfaces/
  sl_bridge/
    server.py                             FastAPI HTTP bridge. Two endpoints:
                                          POST /sl/sensor — stores sensor data,
                                            records location visits on environment posts.
                                          POST /sl/message — loads location history,
                                            calls SensorStore.get_changes() for this user,
                                            builds MessageContext, calls AgentCore.
                                          Always returns HTTP 200 — errors go in the
                                          JSON body to protect LSL's error throttle.
    sensor_store.py   SensorStore         In-memory snapshot of latest sensor data per
                                          region. Tracks per-type update timestamps and
                                          per-user last-delivered timestamps.
                                          get_changes(region, user_id) always returns
                                          environment and rlv (location + avatar state
                                          needed every turn); returns other types only
                                          when updated since the user's last message.
                                          Snapshot includes _ages dict (seconds since
                                          update) surfaced as labels in the system prompt.
    formatters.py                         Grid-aware reply cap: 4000 chars (SL) or 1800
                                          chars (OpenSim). Normalizes Unicode to ASCII.

  discord_bot/
    bot.py          TrixxieBot            discord.py Client. Responds to @mentions
                                          in servers and all DMs. Ignores own messages.
    formatters.py                         Splits long replies into ≤2,000-char chunks
                                          at sentence/paragraph boundaries.

lsl/
  companion_bridge.lsl                    LSL script worn as a HUD by Trixxie's avatar.
                                          Streams sensor data to /sl/sensor: avatars,
                                          environment (region, parcel, description, rating
                                          via llRequestSimulatorData/dataserver), objects
                                          (name, distance, scripted, description, owner),
                                          chat (90s flush + pre-message), rlv (avatar
                                          state: sitting, autopilot, teleport, position).
                                          Listens on channel 42 for /42 conversation —
                                          POSTs to /sl/message, delivers reply via
                                          llInstantMessage (send_chunked).
                                          Also listens on channel 0 for name-trigger
                                          (TRIGGER_NAME substring match) — POSTs to
                                          /sl/message, delivers reply via llSay(0, ...)
                                          (say_chunked) so the conversation remains in
                                          public local chat.

lua/
  trixxie_companion.lua                   Cool VL Viewer automation script.
                                          Copy to user_settings/automation.lua.
                                          OnInstantMsg → PostHTTP → OnHTTPReply → SendIM.
                                          SetAgentTyping wraps inference for typing indicator.
                                          Chat context delivered via HUD sensor pipeline —
                                          no OnReceivedChat buffer in the Lua script.
                                          Replaces the /42 conversation path; sensor HUD
                                          remains required for environmental context.

setup/
  index.html                              Wizard shell — step bar, content area, footer.
  style.css                               Dark theme, toggle switches, platform/tool cards.
  wizard.js                               9-step configuration wizard. Fetches current
                                          config on load, collects state per step, POSTs
                                          to /setup/config on save. Masked secrets pass
                                          through unchanged. Step 1 includes agent name
                                          and owner name (OWNER_NAME env var).
                                          Steps 4–6: Personality, Boundaries, Roleplay —
                                          each a single textarea with a brevity hint.
                                          Step 8: per-platform awareness textareas (only
                                          enabled platforms shown).

interfaces/
  setup_server.py                         FastAPI APIRouter for the setup wizard.
                                          GET /setup, /setup/status, /setup/config.
                                          POST /setup/config — writes .env and
                                          agent_config.json, calls reload_agent_config(),
                                          then runs _migrate_owner_key() which renames any
                                          non-SL_Notes key in person_map.json to SL_Notes
                                          and moves the notes folder accordingly.

  debug_server.py                         FastAPI APIRouter for live agent inspection.
                                          GET /debug — inline HTML debug page (three tabs).
                                          GET /debug/logs — SSE stream of all Python log
                                            records; client-side filter by level + logger.
                                            250ms poll loop; initial comment flushes headers
                                            immediately so EventSource.onopen fires.
                                          GET /debug/sensors — JSON snapshot of all
                                            SensorStore regions with per-type ages.
                                            Sensors tab shows raw JSON (left) and formatted
                                            plain-text panel (right): Objects with name,
                                            description, owner, distance; Avatars with name,
                                            distance; Environment; Chat; Clothing.
                                          GET /debug/prompts — last system prompt, full
                                            messages array (JSON), and exchange per user_id.
                                            Shows char counts per section and total payload
                                            size estimate (~system + messages).
                                            User selected via data-uid attribute on list items.
                                          SSELogHandler bridges logging → asyncio.Queue.
                                          Fan-out broadcaster task copies records to all
                                          connected subscriber queues.
```

---

## Identity and Platform Linking

`data/person_map.json` maps a canonical person ID to all of their platform-specific user IDs:

```json
{
  "SL_Notes": [
    "discord_<snowflake>",
    "sl_<uuid>"
  ]
}
```

On every message, `AgentCore` calls:
- `PersonMap.get_person_id(user_id)` → canonical ID, used to load memory notes
- `PersonMap.get_linked_ids(user_id)` → all other platform IDs, used to load cross-platform context

User IDs are namespaced by platform (`discord_` / `sl_`) to prevent collisions. The person map is the only place where these identities are joined.

---

## The Agentic Tool Loop

Every message from either platform goes through the same loop in `AgentCore._run_tool_loop()`:

```
1. Build messages list = stored history + new user message
2. Call Claude API async (tools enabled, tool_choice="auto")
3. If stop_reason == "end_turn":
      extract text → return
4. If stop_reason == "tool_use":
      for each tool_use block:
          dispatch to tool handler
          if sl_action: append to action_queue (not executed yet)
      append tool_result turn
      go to step 2
5. After MAX_TOOL_ROUNDS (5), force tool_choice="none"
      get final text reply → return
```

The `action_queue` accumulates during the loop. After it ends, the SL interface flushes it — sending each action as an IM or emote via `llInstantMessage`. Discord ignores it.

All turns — including intermediate tool_use and tool_result blocks — are persisted to memory so the full context is replayable on the next message.

---

## Memory

### Conversation Files

History is persisted per `(user_id, channel_id)` pair as JSON files under `data/memory/{safe_user_id}/`. Each file is a `ConversationFile` with a `turns` array of `{role, content}` objects.

`FileMemoryStore` exposes:
- `get_history(user_id, channel_id)` — recent turns for the current conversation
- `get_facts(user_id)` — persisted key/value facts about the user
- `get_all_conversations(user_id)` — all files across all channels (used by the consolidator)
- `append_turn(...)` — appends a turn and trims to `memory_max_history` turns

### Memory Consolidation

`MemoryConsolidator` runs as a background task every 6 hours. The timer is restart-resilient — startup reads `.last_consolidation` timestamp from `data/memory/` and sleeps only the remaining interval, so frequent restarts during development don't reset the 6-hour window.

Consolidation triggers when the **total turns across all files** for a person exceeds **30**. When triggered, it:

1. Collects all conversation files across all linked platform IDs for that person
2. Builds a combined transcript (text turns only — tool_use/tool_result blocks are stripped)
3. Calls Claude to write a first-person journal-style notes file
4. Saves the notes to `data/notes/SL_Notes/memories_YYYY-MM-DD.md`
5. Trims all source conversation files to their most recent **10 turns**

On the next message, `AgentCore._load_memory_notes()` loads the most recent notes file. Rather than passing the full file (potentially several KB), it generates a compact 3–5 bullet summary (≤500 chars) on first use and caches it as `memories_summary_YYYY-MM-DD.md` alongside the source. Subsequent messages use the cached summary. The summary is invalidated when a new `memories_*.md` file appears (next consolidation cycle).

### Cross-Platform Context

`AgentCore._load_cross_platform_context()` fetches the most recently updated conversation from each linked platform. Rather than injecting raw turns, it generates a 1–3 sentence summary (~200 chars) and caches it per uid in `_cross_summary.txt` (format: `{updated_at}\n{summary}`). The cache is invalidated when `updated_at` changes (i.e. a new turn was added on the other platform). This reduces cross-platform context from ~2.5k chars to ~200 chars with no loss of relevant signal.

```
## Recent Conversations on Other Platforms
[DISCORD — last active 2025-04-01]
Discussed SL sim aesthetics and shopping preferences; warm, casual tone.
```

Context is injected into the **static block** of the system prompt (not the messages array — doing so would break the Anthropic API's alternating user/assistant turn requirement).

---

## Location Tracking

`LocationStore` persists a log of every distinct region/parcel Trixxie has visited, stored at `data/memory/{safe_user_id}/locations.json`.

**Write path:** the `/sl/sensor` endpoint calls `location_store.record_visit()` whenever `payload.type == "environment"`. A visit is "new" when the region or parcel differs from the most recent entry. Returning to the same parcel only refreshes `last_visited`. The HUD detects parcel changes via a `last_parcel` global and fires a new env scan within one timer tick (30 s).

**Read path:** the `/sl/message` endpoint calls `location_store.get_recent_visits(limit=10)` and passes the result to `MessageContext.sl_recent_locations`. This surfaces in the system prompt under `## Places You've Visited`.

Deduplication key: `"{region}\x00{parcel}"` — the null byte ensures region and parcel names can never be ambiguously joined.

---

## System Prompt Assembly

**The system prompt is built fresh on every message and split into two Anthropic content blocks.** Block 0 (static: identity, platform rules, memory summary, cross-platform summary, facts) is marked `cache_control: ephemeral` — Anthropic re-caches it when the text changes. Block 1 (dynamic: sensor context + recent locations, SL only) is never cached. The debug page flattens both blocks for display.

The data *inside* the prompt comes from sources with different update frequencies. Some is static, some is live, some may be hours old. The agent receives everything in one block and cannot distinguish freshness except via the age labels injected by `_age_label()`.

### What is sent on every message

| Section | How often the underlying data changes |
|---|---|
| Core persona | Only when the setup wizard is saved and the server reloads `agent_config.json` |
| Platform awareness | Only when wizard is saved — wizard-editable per platform |
| **Environment** (region, parcel, description, rating) | Refreshed on startup, region change, parcel crossing, and every 600s — **always included** regardless of age |
| **RLV / avatar state** (sitting, autopilot, teleport, position) | Refreshed every 30s — **always included** regardless of age |
| Avatars | Refreshed every 150s — included only when updated since the user's last message |
| Objects | Refreshed every 300s — included only when updated since the user's last message |
| Chat | Flushed every 90s and immediately before each message — included only when new lines arrived |
| Clothing | Triggered manually via HUD menu — included only when a new scan result is available |
| Places visited | Written on every environment POST; read at message time from `LocationStore` |
| Additional context | Only when wizard is saved |
| Memory notes | Written by `MemoryConsolidator` every 6 hours when threshold is met; loaded from the most recent file on disk |
| Cross-platform context | 1–3 sentence summary cached per uid; invalidated when new turns arrive |
| Known facts | Updated whenever the agent calls `upsert_fact`; loaded fresh at message time |

### Timing summary

```
Message received
       │
       ├── load history + facts from disk          (current state)
       ├── load memory notes from disk             (up to 6h old)
       ├── load cross-platform context from disk   (up to last conversation)
       ├── SensorStore.get_changes()               (environment: up to 600s old
       │                                            rlv: up to 30s old
       │                                            others: only if updated)
       ├── LocationStore.get_recent_visits()       (current state)
       │
       └── build_system_prompt_blocks() → [static block (cached), dynamic block]
                                                    → Claude API call
```

The age labels in the sensor context (`[47s ago]`, `[4m ago]`) are the only signal to the agent about data freshness. Environment and RLV are always present so the agent always knows where it is and what state it's in, even during a fast back-and-forth conversation where no other sensors have updated.

The platform awareness block tells the agent what it can perceive, what it cannot do, and how to behave on the current platform. It is wizard-editable per platform (discord / sl / opensim) and injected as a single markdown section from `cfg["platform_awareness"][platform]`.

### Section order (as assembled by `build_system_prompt_blocks()`)

**Block 0 — static, `cache_control: ephemeral`**

| # | Section | Source | Condition |
|---|---|---|---|
| 1 | Core persona | `_build_core_block(cfg)` from `agent_config.json` | Always |
| 2 | Platform awareness | `_get_platform_awareness(cfg, platform)` — wizard-editable per platform | If non-empty |
| 3 | Additional context | `cfg["additional_context"]` | If non-empty |
| 4 | Memory notes | `memories_summary_*.md` (≤500 chars) | If consolidated notes exist |
| 5 | Cross-platform context | 1–3 sentence summary from `_cross_summary.txt` | If linked IDs exist |
| 6 | Known facts | `memory.get_facts(user_id)` | If non-empty |

**Block 1 — dynamic, no cache (SL only)**

| # | Section | Source | Condition |
|---|---|---|---|
| 7 | Sensor context | `SensorStore.get_changes()` — objects grouped by (name,owner) | SL only, if non-empty |
| 8 | Places visited | `LocationStore.get_recent_visits()` | SL only, if non-empty |

---

## Second Life Communication Flow

### Via LSL HUD (channel 42)

```
StonedGrits types: /42 hey what do you think of this sim?
        │
        ▼
Trixxie's HUD (LSL, channel 42 listener)
        │  llHTTPRequest POST /sl/message  [X-SL-Secret header]
        ▼
cloudflared tunnel  →  FastAPI bridge (localhost:8080)
        │
        ├── SensorStore.get_changes(region, uid)   ← only types updated since last msg
        ├── LocationStore.get_recent_visits(uid)   ← SL visit history
        │
        ▼
AgentCore.handle_message()
        │  builds system prompt with persona + self-awareness + sensor + memory + locations
        ▼
Model API  →  reply text (+ optional sl_actions)
        │
        ▼
FastAPI returns JSON: { "reply": "...", "actions": [...] }
        │
        ▼
LSL HUD receives http_response
        │  llInstantMessage(StonedGrits_key, reply)
        ▼
Private IM arrives in StonedGrits' chat window
```

### Via Cool VL Viewer Lua (direct IM)

```
StonedGrits sends a private IM to Trixxie's avatar
        │
        ▼
automation.lua — OnInstantMsg(session_id, origin_id, type=0, ...)
        │  SetAgentTyping(true)   ← typing indicator appears
        │  PostHTTP POST /sl/message  [secret in body]
        ▼
cloudflared tunnel  →  FastAPI bridge (localhost:8080)
        │
        ├── SensorStore.get_changes(region, uid)   ← only types updated since last msg
        ├── LocationStore.get_recent_visits(uid)   ← SL visit history
        │
        ▼
AgentCore.handle_message()
        ▼
Claude API  →  reply text
        │
        ▼
FastAPI returns JSON: { "reply": "...", "actions": [...] }
        │
        ▼
automation.lua — OnHTTPReply(handle, success, reply)
        │  SetAgentTyping(false)  ← typing indicator clears
        │  SendIM(session_id, chunk) × N
        ▼
Reply arrives in StonedGrits' IM window — no /42 required
```

Sensor data travels a separate path in both cases — the HUD POSTs to `/sl/sensor` on independent timers and on location changes. The `/sl/message` endpoint calls `SensorStore.get_changes()` which returns only sensor types updated since that user's last message. Chat is no longer piggybacked on `/42` or IM payloads — it is flushed via `do_chat_flush()` to `/sl/sensor` every 90 seconds and immediately before each `/42` POST.

---

## Platform Differences

| Concern | Discord | SL — LSL HUD | SL — Lua script |
|---|---|---|---|
| Input trigger | @mention, DM, or active channel | `/42 message` in local chat | Private IM to avatar |
| Output delivery | `channel.send()`, chunked ≤2,000 chars | `llInstantMessage`, chunked ≤1,000 chars | `SendIM`, chunked ≤1,000 chars |
| Typing indicator | No | No | Yes — `SetAgentTyping` |
| Auth mechanism | N/A | `X-SL-Secret` HTTP header | `secret` field in JSON body |
| Unicode | Markdown supported | Normalized to ASCII | Normalized to ASCII |
| `sl_action` tool | Not available | Available — queued, sent after reply | Available — queued, sent after reply |
| Sensor context | Not available | environment (region, parcel, description, rating) + rlv always; avatars, objects (description+owner), chat, clothing when changed | From HUD snapshots via get_changes() |
| Location history | Not available | Recent 10 parcels injected into prompt | Recent 10 parcels injected into prompt |
| User ID prefix | `discord_` | `sl_` | `sl_` |
| Active channel config | `DISCORD_ACTIVE_CHANNEL_IDS` in `.env` | N/A | N/A |

`MessageContext.platform` is the single field that drives all of these differences. The core agent has no platform-specific logic.

---

## Threading / Async Model

The application is fully async (asyncio). The Anthropic client is `AsyncAnthropic` — API calls are non-blocking awaitable coroutines, keeping the Discord WebSocket heartbeat and SL bridge responsive during inference.

```
asyncio event loop
  ├── consolidation_loop()        (restart-resilient, every 6 hours)
  ├── debug_server._broadcaster() (SSE log fan-out, always running)
  ├── discord.py tasks            (fully async)
  └── uvicorn                     (FastAPI HTTP bridge, async)
        ├── POST /sl/sensor → SensorStore.update()
        ├── POST /sl/message → AgentCore.handle_message() (async)
        ├── GET  /debug/logs → SSE StreamingResponse
        └── GET  /setup/* → wizard API
```

All three services share the same `AgentCore`, `FileMemoryStore`, and `LocationStore` instances. Concurrent writes to the same memory file are serialised by per-(user, channel) `asyncio.Lock` in `FileMemoryStore`. `LocationStore` uses a per-user `asyncio.Lock` for the same reason.

---

## Security Notes

- **`.env` is gitignored.** API keys never touch version control.
- **SL HTTP bridge** uses an optional shared secret in the `X-SL-Secret` header. Always returns HTTP 200 — errors go in the JSON body to avoid burning LSL's 5-errors-in-60s throttle.
- **Rate limiting** is per-user in-memory token bucket. Not persistent across restarts — by design (soft throttle, not a hard block).

---

## Known Constraints

| Constraint | Detail |
|---|---|
| SL direct IMs (LSL path) | LSL cannot intercept IMs sent directly to an avatar. Channel 42 is the interaction mechanism for the LSL HUD. The Cool VL Viewer Lua script solves this — it uses `OnInstantMsg` to receive private IMs natively. |
| Tunnel URL changes | Free cloudflared tunnels get a new URL on each restart. A named tunnel (paid or self-hosted) gives a permanent URL and avoids updating the LSL script. |
| Avatar scan cap | Avatar list is capped at 25 nearest to prevent Stack-Heap Collision in crowded sims (up to 100 avatars). |
| Consolidation is person-wide | Trimming conversation files to 10 turns affects all platforms for that person simultaneously. |

---

## Future Considerations

| Area | Notes |
|---|---|
| Radegast C# plugin | Native IM loop for Radegast viewer — same `/sl/message` endpoint; requires C# build pipeline |
| Memory upgrade | Swap `FileMemoryStore` → `ChromaMemoryStore` in `main.py` — `AbstractMemoryStore` is the only contract `AgentCore` depends on |
| Named tunnel | Permanent subdomain so the LSL `SERVER_URL` never needs updating |
| More tools | Register a new handler in `ToolRegistry` and add a schema in `tools.py` |
| Web dashboard | Memory and location files are plain JSON — readable by any future UI layer |
| Proactive agent loop | See below |

---

## Proactive Agent Loop (Future)

Currently the agent is purely reactive — it only processes a message when a user sends one. Sensor data accumulates in `SensorStore` continuously but the agent never sees it unless a message arrives. The proactive loop removes that dependency.

### Concept

A background asyncio task runs alongside the existing services. On a configurable interval (e.g. every 60 seconds), it inspects `SensorStore` for significant changes — new avatars entering range, a teleport detected in the RLV state, a leash autopilot starting, a notable chat line — and if a threshold is met, calls `AgentCore.handle_message()` with a synthetic context message. The agent produces a response, which is queued for delivery to the HUD.

```
asyncio event loop
  ├── consolidation_loop()        (every 6 hours)
  ├── proactive_loop()            (every N seconds — future)
  │     ├── inspect SensorStore for significant deltas
  │     ├── if threshold met → AgentCore.handle_message(synthetic_msg, context)
  │     └── queue response → pending_ims[owner_uuid]
  ├── debug_server._broadcaster()
  ├── discord.py tasks
  └── uvicorn
        ├── POST /sl/sensor → SensorStore.update()
        ├── POST /sl/message → AgentCore.handle_message()
        └── GET  /sl/poll   → drain pending_ims[user_id]  (future)
```

### Delivery problem

The server cannot push an IM to Second Life on its own — LSL `llHTTPRequest` is outbound-only and `llInstantMessage` must be called from within the script. Two approaches:

**Option A — HUD polling:** Add a `GET /sl/poll` endpoint. The HUD calls it on a timer (e.g. every 10s) and delivers any queued proactive messages via `llInstantMessage`. No new channel required. Latency is bounded by the poll interval.

**Option B — Dedicated push channel:** The HUD listens on a second private channel (e.g. channel 43). The server POSTs to a new `/sl/push` endpoint; the HUD's `http_response` handler calls `llInstantMessage` with the body. Lower latency but requires an additional outbound POST per proactive message.

### What the agent can react to proactively

- A new avatar entering range (avatars sensor delta)
- An avatar leaving — someone walked away mid-conversation
- Teleport detected in RLV state — likely a leash drag or force-TP
- Autopilot started — being walked on a leash
- Sitting on a new object — force-sit by a collar or piece of furniture
- Chat on channel 0 from a non-user — someone spoke nearby without using `/42`

### Key design constraints

- Proactive calls use the same `AgentCore.handle_message()` path — full tool loop, memory, system prompt
- A synthetic `user_id` (e.g. `sl_proactive`) or the owner's UUID can be used; using the owner's UUID means proactive turns appear in the same conversation history
- The rate limiter and `reply_http` lock must be respected — proactive calls should not fire while a user message is in flight
- The agent needs clear framing in the synthetic message: `"[Sensor update — no user message] A new avatar entered range: ..."` so it understands it is initiating, not responding
