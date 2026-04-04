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

  persona.py        Persona      Trixxie's identity. Builds the system prompt from
                                 static text blocks + runtime-injected context.
                                 MessageContext carries platform, user, channel,
                                 sensor data, and recent location history.

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
  notes/{person_id}/
    memories_YYYY-MM-DD.md                Consolidated memory notes written by Claude.

interfaces/
  sl_bridge/
    server.py                             FastAPI HTTP bridge. Two endpoints:
                                          POST /sl/sensor — stores sensor data,
                                            records location visits on environment posts.
                                          POST /sl/message — loads location history,
                                            builds MessageContext, calls AgentCore.
                                          Always returns HTTP 200 — errors go in the
                                          JSON body to protect LSL's error throttle.
    sensor_store.py   SensorStore         In-memory snapshot of latest sensor data
                                          per region. Passed into MessageContext.
    formatters.py                         Trims reply to SL's 1,023-char IM limit.
                                          Normalizes Unicode to ASCII for SL compat.

  discord_bot/
    bot.py          TrixxieBot            discord.py Client. Responds to @mentions
                                          in servers and all DMs. Ignores own messages.
    formatters.py                         Splits long replies into ≤2,000-char chunks
                                          at sentence/paragraph boundaries.

lsl/
  companion_bridge.lsl                    LSL script worn as a HUD by Trixxie's avatar.
                                          Streams sensor data to /sl/sensor.
                                          Listens on channel 42 for conversation.
                                          POSTs to /sl/message, receives JSON reply,
                                          delivers response via llInstantMessage.

lua/
  trixxie_companion.lua                   Cool VL Viewer automation script.
                                          Copy to user_settings/automation.lua.
                                          OnInstantMsg → PostHTTP → OnHTTPReply → SendIM.
                                          SetAgentTyping wraps inference for typing indicator.
                                          OnReceivedChat feeds ambient chat buffer.
                                          Replaces the /42 conversation path; sensor HUD
                                          remains required for environmental context.
```

---

## Identity and Platform Linking

`data/person_map.json` maps a canonical person ID to all of their platform-specific user IDs:

```json
{
  "pablorios": [
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

`MemoryConsolidator` runs as a background task every 6 hours. When any single conversation file for a person exceeds **40 turns**, it:

1. Collects all conversation files across all linked platform IDs for that person
2. Builds a combined transcript (text turns only — tool_use/tool_result blocks are stripped)
3. Calls Claude to write a first-person journal-style notes file
4. Saves the notes to `data/notes/{person_id}/memories_YYYY-MM-DD.md`
5. Trims all source conversation files to their most recent **10 turns**

On the next message, `AgentCore._load_memory_notes()` loads the most recent notes file. This gives Trixxie long-term recall without unbounded conversation files.

### Cross-Platform Context

`AgentCore._load_cross_platform_context()` fetches the most recently updated conversation from each linked platform. The last **15 turns** are formatted as a labelled block and injected into the **system prompt** (not the messages array — doing so would break the Anthropic API's alternating user/assistant turn requirement).

```
## Recent Conversations on Other Platforms
[DISCORD — last active 2025-04-01]
User: ...
Trixxie: ...
```

This gives Trixxie continuity across platforms without being explicitly told what was discussed elsewhere.

---

## Location Tracking

`LocationStore` persists a log of every distinct region/parcel Trixxie has visited, stored at `data/memory/{safe_user_id}/locations.json`.

**Write path:** the `/sl/sensor` endpoint calls `location_store.record_visit()` whenever `payload.type == "environment"`. A visit is "new" when the region or parcel differs from the most recent entry. Returning to the same parcel only refreshes `last_visited`. The HUD detects parcel changes via a `last_parcel` global and fires a new env scan within one timer tick (30 s).

**Read path:** the `/sl/message` endpoint calls `location_store.get_recent_visits(limit=10)` and passes the result to `MessageContext.sl_recent_locations`. This surfaces in the system prompt under `## Places You've Visited`.

Deduplication key: `"{region}\x00{parcel}"` — the null byte ensures region and parcel names can never be ambiguously joined.

---

## System Prompt Assembly

`build_system_prompt()` in `core/persona.py` assembles the final system prompt in this order:

| Section | Source | Condition |
|---|---|---|
| Core persona | `TRIXXIE_CORE` constant | Always |
| Platform addendum | `SL_ADDENDUM` or `DISCORD_ADDENDUM` | Always |
| Current sim | `context.sl_region` | SL only |
| Nearby chat | `context.sl_nearby_chat[-10:]` | SL only, if non-empty |
| Sensor context | `context.sl_sensor_context` | SL only, if non-empty |
| Places visited | `context.sl_recent_locations` | SL only, if non-empty |
| Memory notes | `data/notes/{person_id}/memories_*.md` | If consolidated notes exist |
| Cross-platform context | Recent turns from linked platform(s) | If linked IDs exist |
| Known facts | `memory.get_facts(user_id)` | If non-empty |

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
        ├── SensorStore.get_snapshot(region)       ← latest sensor data
        ├── LocationStore.get_recent_visits(uid)   ← SL visit history
        │
        ▼
AgentCore.handle_message()
        │  builds system prompt with persona + sensor + memory + locations
        ▼
Claude API  →  reply text (+ optional sl_actions)
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
        ├── SensorStore.get_snapshot(region)       ← latest sensor data (from HUD)
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

Sensor data travels a separate path in both cases — the HUD POSTs to `/sl/sensor` on a timer and on location changes. The `/sl/message` endpoint reads the latest snapshot from `SensorStore` at request time.

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
| Sensor context | Not available | Full (avatars, env, objects, clothing) | From HUD snapshots (HUD still required) |
| Location history | Not available | Recent 10 parcels injected into prompt | Recent 10 parcels injected into prompt |
| User ID prefix | `discord_` | `sl_` | `sl_` |
| Active channel config | `DISCORD_ACTIVE_CHANNEL_IDS` in `.env` | N/A | N/A |

`MessageContext.platform` is the single field that drives all of these differences. The core agent has no platform-specific logic.

---

## Threading / Async Model

The application is fully async (asyncio). The Anthropic client is `AsyncAnthropic` — API calls are non-blocking awaitable coroutines, keeping the Discord WebSocket heartbeat and SL bridge responsive during inference.

```
asyncio event loop
  ├── consolidation_loop()  (every 6 hours)
  ├── discord.py tasks      (fully async)
  └── uvicorn               (FastAPI HTTP bridge, async)
        └── POST /sl/message → AgentCore.handle_message() (async)
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
