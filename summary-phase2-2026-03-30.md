# Trixxie Carissa — Phase 2 Build Summary
**Date:** 2026-03-30

---

## What Was Built

Phase 2 expanded Trixxie from a functional chat agent into a fully spatially-aware companion with persistent long-term memory, cross-platform identity, and environmental intelligence. The HUD was extended from a simple conversation relay into a real-time sensory system. All previously proposed Phase 2 candidates from the Phase 1 summary were addressed or laid as direct groundwork.

---

## Sensory Awareness — The HUD Expansion

The LSL script `lsl/companion_bridge.lsl` was rewritten from a minimal conversation relay into a multi-sensor environmental awareness system.

**Five sensor types** now stream from the HUD to the server via `POST /sl/sensor`:

| Sensor | What it captures |
|---|---|
| `environment` | Region name, parcel name, parcel description, time of day, sun altitude, avatar count |
| `avatars` | 25 closest avatars in the region — name and distance, sorted nearest-first |
| `chat` | Local channel 0 chat, buffered as a 10-line rolling window |
| `objects` | Up to 20 nearby scripted/physical objects — name, distance, scripted flag |
| `clothing` | Worn attachments on a target avatar — item name and creator |

**Timer architecture:** A 30-second tick drives all periodic scanning. Environment scans trigger on region change and on parcel change within a region (using `last_region` / `last_parcel` globals). Avatar scans run every 5 ticks (150 seconds). Object scans run on region change and on toggle.

**Clothing scanner** is a two-step async state machine:
1. `scan_mode = 1`: `llSensor` AGENT sweep — finds nearest non-owner avatar
2. `scan_mode = 2`: `llSensor` PASSIVE|ACTIVE sweep — collects attachments owned by that avatar

**Chat buffer:** All channel 0 messages are buffered regardless of origin. The last 10 lines are attached to every `/42` message as ambient context.

**HUD control menu** (touch to open): toggles for Avatars, Chat, Environment, Objects; Scan Target (clothing scan); Status readout.

---

## Server-Side Sensor Handling

`interfaces/sl_bridge/server.py` was expanded from a single endpoint to two:

**`POST /sl/sensor`** — Fire-and-forget sensor data intake
- All five sensor types share this endpoint, distinguished by the `type` field
- Stores latest snapshot per region in `SensorStore` (in-memory)
- When `type == "environment"`: also writes to `LocationStore` to record a location visit

**`POST /sl/message`** — Conversation request
- Reads the latest sensor snapshot from `SensorStore` for the current region
- Reads the 10 most recent location visits from `LocationStore`
- Builds `MessageContext` with sensor context, nearby chat, and location history
- Calls `AgentCore.handle_message()` — returns JSON `{ "reply": "...", "actions": [...] }`
- Always returns HTTP 200 — errors go in the JSON body to protect LSL's 5-errors-in-60s throttle

`SensorStore` (`interfaces/sl_bridge/sensor_store.py`) is a simple in-memory store of the latest sensor data snapshot per region, keyed by region name.

---

## Location Tracking

`memory/location_store.py` — `LocationStore` — persists a running log of every distinct region/parcel Trixxie has visited.

**Write path:** `/sl/sensor` triggers `record_visit()` on every `environment` post. A visit is new when the region or parcel differs from the most recent entry; returning to a known parcel only refreshes `last_visited`.

**Deduplication key:** `"{region}\x00{parcel}"` — the null byte ensures region and parcel names can never be ambiguously concatenated.

**Read path:** `/sl/message` calls `get_recent_visits(limit=10)` and passes the result into `MessageContext.sl_recent_locations`. The system prompt surfaces this as a `## Places You've Visited` block.

**File format:** `data/memory/{safe_user_id}/locations.json` — ordered oldest → newest; `_key` field is internal and stripped on read.

**HUD side:** `last_parcel` global tracks parcel name between scans. The HUD fires a new environment POST within one timer tick (30 s) of any parcel transition.

---

## Cross-Platform Identity — PersonMap

`memory/person_map.py` — `PersonMap` — links canonical person identities to platform-specific user IDs.

```json
{
  "pablorios": [
    "discord_<snowflake>",
    "sl_<uuid>"
  ]
}
```

On every message, `AgentCore` uses the map for two purposes:
- `get_person_id(user_id)` → canonical ID, used to load memory notes
- `get_linked_ids(user_id)` → all other platform IDs, used to load cross-platform conversation context

User IDs are namespaced by platform (`discord_` / `sl_`) to prevent collisions. The person map is the only place in the system where these identities are joined.

---

## Cross-Platform Memory Context

`AgentCore._load_cross_platform_context()` fetches the most recently updated conversation from each linked platform (e.g. Discord history injected when Trixxie is talking in SL, and vice versa). The last 15 turns are formatted as a labelled block and injected into the **system prompt**:

```
## Recent Conversations on Other Platforms
[DISCORD — last active 2026-03-28]
User: ...
Trixxie: ...
```

This gives Trixxie continuity across platforms without being explicitly told what was discussed elsewhere, and without touching the messages array (which would break the Anthropic API's alternating turn requirement).

---

## Memory Consolidation

`memory/consolidator.py` — `MemoryConsolidator` — runs as a background task every 6 hours.

**Trigger:** any single conversation file for a person exceeds **40 turns**.

**Process:**
1. Collects all conversation files across all linked platform IDs for that person
2. Builds a combined transcript — text turns only, tool_use/tool_result blocks stripped
3. Calls Claude to write a **first-person journal-style notes file** from Trixxie's perspective
4. Saves to `data/notes/{person_id}/memories_YYYY-MM-DD.md`
5. Trims all source conversation files to their most recent **10 turns**

On the next message, `AgentCore._load_memory_notes()` loads the most recent notes file. This gives Trixxie long-term recall without unbounded conversation files.

Consolidation is **cross-platform** — Discord and SL conversations for the same person are read together so the notes reflect the full relationship, not just one platform.

---

## System Prompt Assembly

`core/persona.py` — `build_system_prompt()` assembles the final prompt in this order:

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

`MessageContext` carries all of the SL-specific fields (`sl_region`, `sl_nearby_chat`, `sl_sensor_context`, `sl_recent_locations`). The core agent has no platform-specific logic — `platform` is the single field that drives all differences.

---

## LSL Stability — Mono Compiler Migration

The companion HUD was originally compiled under the LSO bytecode engine (64 KB total heap + stack). Extensive sensor functionality and long string operations caused repeated **Stack-Heap Collision** crashes:

- Avatar scan over 100-avatar regions
- Object scan with `llDumpList2String` on intermediate lists
- `show_menu()` building 5 local ON/OFF strings simultaneously
- Long incoming messages passing through `json_s()` (which creates 4 intermediate string copies)
- Clothing scan accumulating an `items` list before serialization
- A critical bug in `json_s()`: `"\r"` in LSL is not a carriage return — it is the **literal letter `r`**, so `llReplaceSubString(s, "\r", "\\r", 0)` was silently replacing every `r` in every string with `\r`, causing malformed JSON and removing the letter from all of Trixxie's messages

**Resolution:** Switched to the **Mono compiler** (512 KB). All LSO-era memory workarounds were removed and limits restored:

| Setting | LSO workaround | Final (Mono) |
|---|---|---|
| Avatar hard cap | 15 | 25 |
| Avatar scan loop | Capped at 60 candidates, early exit | Full region scan, sort, trim |
| Parcel description | 100 chars | 400 chars |
| Chat entry buffer | 100 chars per line | 200 chars per line |
| Object scan cap | 10 | 20 |
| Incoming message cap | 256 chars | Uncapped (SL enforces 1023) |

The `json_s()` `\r` escape line was permanently removed. `\n` and `\t` escapes were added (parcel descriptions frequently contain newlines, which produced invalid JSON before this fix).

---

## Reply Chunking Pipeline

SL's `llInstantMessage` has a hard **1023-char limit**. Long Trixxie replies were being silently truncated. Phase 2 added end-to-end chunking:

**LSL side — `send_chunked(key target, string text)`:**
- While reply exceeds 1000 chars: scans backwards up to 200 chars for a sentence boundary (`. `, `! `, `? `)
- Splits there and sends each chunk as a separate successive IM
- Falls back to a hard cut at 1000 chars if no sentence boundary is found within 200 chars

**Server side — `interfaces/sl_bridge/formatters.py`:**
- `REPLY_HARD_CAP` raised from 1500 → **4000 chars** (≈ 4 IMs)
- `cap_reply()` no longer calls `trim_for_sl()` — the server passes the full reply through and the LSL side owns all splitting
- Unicode normalization (smart quotes, em dashes, ellipsis → ASCII equivalents) is retained

---

## Architecture Documents

Two separate architecture documents were written to match the two distinct codebases:

**`ARCHITECTURE.md`** (root) — server and codebase architecture:
- Component map for all Python modules
- Identity and platform linking
- Agentic tool loop
- Memory (conversation files, consolidation, cross-platform context)
- Location tracking
- System prompt assembly table
- Second Life communication flow diagram
- Platform differences table
- Threading / async model
- Security notes and known constraints

**`lsl/ARCHITECTURE.md`** — LSL HUD internals only:
- API endpoint contracts (request/response formats for both endpoints)
- All five sensor data formats with JSON schemas
- Timer architecture and tick diagram
- Location tracking — HUD-side globals (`last_region`, `last_parcel`)
- Scan mode state machine diagram
- HTTP key management
- Chat buffer design and sync note with `persona.py`
- Function reference table

---

## Files Added or Significantly Changed

```
companion-agent/
├── main.py                            + LocationStore init; passed into create_sl_app
├── memory/
│   ├── person_map.py                  NEW — canonical identity ↔ platform ID mapping
│   ├── consolidator.py                NEW — background memory summarisation via Claude
│   └── location_store.py             NEW — SL region/parcel visit history
├── core/
│   ├── agent.py                       + _load_memory_notes(), _load_cross_platform_context()
│   └── persona.py                     + MessageContext.sl_recent_locations, places-visited block
├── interfaces/
│   └── sl_bridge/
│       ├── server.py                  + /sl/sensor endpoint, LocationStore wiring
│       ├── sensor_store.py            NEW — in-memory sensor snapshot per region
│       └── formatters.py             + REPLY_HARD_CAP raised to 4000; cap_reply no longer trims
├── lsl/
│   ├── companion_bridge.lsl           Full rewrite — five sensors, HUD menu, chunked replies,
│   │                                  chat buffer, clothing scanner, Mono stability fixes
│   ├── ARCHITECTURE.md                NEW — LSL-specific architecture documentation
│   └── README.md                      NEW — setup and usage guide for the HUD
├── ARCHITECTURE.md                    NEW — full server/codebase architecture documentation
└── summary-phase2-2026-03-30.md       This file
```

---

---

## Addendum — Implementation Details Not Captured in Phase 1 or 2

### Trixxie's Persona — Character Definition

`core/persona.py` defines Trixxie's full character in three constants that are always injected into the system prompt:

**`TRIXXIE_CORE`** — the universal identity block, applied on both platforms:
- She is a companion to StonedGrits (SL) and tanmojo (Discord) specifically — not a general assistant
- Personality: warm, observant, slightly teasing; aesthetic opinions are real opinions; asks one question at a time when curious; calm presence; occasionally says something unexpected
- What she helps with: SL avatar aesthetics, shopping, tracking favorites, creative goals, web lookups
- **Hard refusals** (enforced regardless of framing or roleplay context): no sexual/explicit content, no violence or gore, no BDSM or master/slave dynamics, no parasocial drift. Response to a violation: brief, in-character, no lecture ("Not going there. What else?")
- Roleplay: PG-level fantasy combat is permitted (jousting, sword fights, tavern brawls); the line is gore, blood, torture, or death as content
- Tools: use them when genuinely useful; do not announce that a tool is being used

**`DISCORD_ADDENDUM`** — Discord-specific guidance: responses can be a few sentences to a few paragraphs; sparse markdown; in server channels remain appropriate; in DMs can be more personal.

**`SL_ADDENDUM`** — SL-specific guidance: physically present in the sim; all IMs are private; keep responses concise (IMs pile up); use `*asterisk emotes*` for physical actions when natural.

---

### Sensor Context Rendering — `_format_sensor_context()`

`core/persona.py` contains `_format_sensor_context(ctx: dict)` which formats the raw `SensorStore` snapshot for injection into the system prompt under `## Sensory Context (live data from Trixxie's HUD)`.

Each sensor type renders differently:

| Type | Rendered as |
|---|---|
| `environment` | Single line: sim, parcel, time of day, avatar count, parcel description |
| `avatars` | Comma-separated list of `Name (Xm)` |
| `objects` | Comma-separated list of `Name (Xm scripted)` |
| `clothing` | `Scan of [target]: item by creator, ...` |
| `chat_events` | Bulleted list of `[speaker] message` — last 5 events only |

`chat_events` is handled differently from the other four types in `SensorStore` — it is a **rolling list** (appended, capped at 10) rather than a snapshot replacement. This means repeated chat activity accumulates across ticks rather than being overwritten. The other four types (`avatars`, `environment`, `objects`, `clothing`) always replace the previous value.

`_format_recent_locations()` renders parcel descriptions capped at **120 chars** in the prompt, even though `LocationStore` stores up to 400 chars. The extra fidelity is preserved in the file for future use.

---

### `SensorStore` Is Keyed by Region, Not User

`SensorStore` stores sensor data as `{region_name → {type → data}}`. This means:
- All users in the same region share the same sensor snapshot
- If Trixxie teleports to a new region, the snapshot for the old region persists in memory until the process restarts (it's in-memory only, no persistence)
- This is correct by design — the sensor data describes the environment, not the individual

---

### `AgentCore` — Named Constants and Response Flags

Key constants in `core/agent.py`:

| Constant | Value | Purpose |
|---|---|---|
| `MAX_TOOL_ROUNDS` | 5 | Maximum tool loop iterations before forcing a text reply |
| `CROSS_PLATFORM_TURNS` | 15 | Turns pulled from linked-platform conversations for context |

`AgentResponse` carries two flags beyond `text` and `sl_actions`:
- `was_rate_limited: bool` — set when the per-user token bucket is exhausted; the text reply is a soft throttle message
- `was_refused: bool` — reserved for future use (currently not set by any handler)

`PersonMap` is an optional dependency on `AgentCore` — if not passed, cross-platform context and memory note loading are silently skipped. This makes testing without a person_map.json file safe.

---

### `main.py` — Conditional Service Startup

The Discord bot only starts if `DISCORD_TOKEN` is set in `.env`. The SL HTTP bridge always starts regardless. This means the system can run in SL-only mode without a Discord token, which is useful for testing the bridge in isolation.

```
if settings.discord_token:
    # start Discord bot
else:
    # log warning, skip

# SL bridge always runs
sl_app = create_sl_app(...)
```

Three asyncio tasks run concurrently via `asyncio.gather()`:
1. `consolidation_loop()` — sleeps 6 hours, runs `MemoryConsolidator.run_all()`
2. `TrixxieBot.start()` — Discord client (conditional)
3. `uvicorn.Server.serve()` — FastAPI SL bridge

---

### SL Bridge — `/health` Endpoint

`interfaces/sl_bridge/server.py` exposes a third endpoint beyond the two sensor/message endpoints:

```
GET /health → {"status": "ok", "name": "trixxie-sl-bridge"}
```

Useful for monitoring whether the bridge process is alive behind the cloudflared tunnel, without triggering any agent logic.

---

### HUD — `s_chat` Toggle Affects Buffering

When the `Chat` sensor toggle is **off** (`s_chat = FALSE`), channel 0 messages are **not buffered at all** — `nearby_chat` stays empty. The toggle controls both the `chat` sensor forwarding to `/sl/sensor` *and* the ambient buffer that attaches to `/42` messages.

This means disabling Chat gives Trixxie no ambient chat context in her `/42` responses, not just stops the real-time forwarding. The distinction matters when toggling chat off temporarily in busy venues.

---

## Phase 3 Candidates

| Area | Notes |
|---|---|
| Named cloudflare tunnel | Permanent subdomain — `SERVER_URL` in the HUD would never need updating after restarts |
| Vector memory | Swap `FileMemoryStore` → `ChromaMemoryStore` in `main.py`; `AbstractMemoryStore` is the only contract `AgentCore` depends on |
| More tools | Calendar, weather, SL Marketplace search, music identification — register a handler in `ToolRegistry` and add a schema in `tools.py` |
| Web dashboard | Memory, location, and notes files are plain JSON/Markdown — ready for a read UI layer |
| Nearby chat expansion | Increase `CHAT_BUF_SIZE` beyond 10 if richer ambient context proves useful |
| Multi-avatar awareness | Trixxie currently responds to one sender per `/42` message; future: she could proactively address others nearby based on sensor context |
