# Trixxie Carissa — Companion Agent

AI companion powered by Claude (claude-sonnet-4-6), running simultaneously on Discord and Second Life via a shared AgentCore. This is a personal project turned into a general-purpose framework.

## Run

```bash
./run.sh          # activates .venv and starts main.py
python main.py    # manual equivalent
```

SL bridge always starts. Discord bot only starts if `DISCORD_TOKEN` is set.

## Key Files

```
main.py                          Entry point — asyncio.gather() over three tasks
config/settings.py               All config loaded from .env via load_settings()
core/agent.py                    AgentCore — shared brain, async tool loop (MAX_TOOL_ROUNDS=5)
core/persona.py                  System prompt assembly + MessageContext dataclass
core/tools.py                    ToolRegistry — platform-filtered tool dispatch
memory/file_store.py             FileMemoryStore — JSON files, per-(user,channel) asyncio.Lock
memory/consolidator.py           MemoryConsolidator — background Claude-written notes (6h)
memory/person_map.py             PersonMap — links Discord + SL IDs to canonical person
memory/location_store.py         LocationStore — SL region/parcel visit history
interfaces/discord_bot/bot.py    TrixxieBot — discord.py client
interfaces/sl_bridge/server.py   FastAPI bridge — /sl/message and /sl/sensor endpoints
interfaces/sl_bridge/sensor_store.py  SensorStore — in-memory sensor snapshot per region
lsl/companion_bridge.lsl         LSL HUD script worn by Trixxie's avatar (Mono compiler)
data/person_map.json             Canonical identity → platform user ID list
```

## Architecture in One Paragraph

Every message (Discord @mention/DM or SL /42 channel) goes through `AgentCore.handle_message()`. It loads history, facts, memory notes, and cross-platform context, builds the system prompt via `build_system_prompt()`, then runs the Anthropic async tool loop. All turns including tool_use/tool_result blocks are persisted. The SL bridge also receives fire-and-forget sensor POSTs from the HUD (avatars, environment, chat, objects, clothing) which are stored in `SensorStore` and injected into the system prompt on the next message.

## Platform Rules

- User IDs are namespaced: `discord_{snowflake}` and `sl_{uuid}`
- `MessageContext.platform` is the single field that drives all platform differences
- `sl_action` tool is only available when `platform == "sl"`
- SL bridge always returns HTTP 200 — errors go in the JSON body (LSL throttle protection)

## Memory Layout

```
data/memory/{safe_user_id}/
    {channel_id}.json       conversation turns
    _facts.json             persistent key/value facts
    locations.json          SL visit history (LocationStore)
data/notes/{person_id}/
    memories_YYYY-MM-DD.md  Claude-written consolidated notes
```

Consolidation triggers when any conversation file exceeds 40 turns. Trims all files for that person to 10 turns after writing notes.

## LSL Script Constraints (lsl/companion_bridge.lsl)

- Compiled with **Mono** (512 KB) — not LSO (64 KB). Do not reintroduce LSO-era memory caps.
- `json_s()` escapes `\\ " \n \t` only — `\r` is NOT a valid escape in LSL (it is the literal letter r).
- Avatar scan: 25 closest in region, sorted by distance via `llGetAgentList` + `llGetObjectDetails`.
- Reply chunking: `send_chunked()` splits at sentence boundaries (≤1000 chars per IM).
- Chat buffer: 10-line rolling window on channel 0, pre-escaped on store.
- `SECRET` and `SERVER_URL` are set at the top of the script; `SECRET` must match `SL_BRIDGE_SECRET`.

## Python Conventions

- Always `AsyncAnthropic` — never the sync client. The sync client blocks the event loop.
- Concurrent writes to memory files are serialized by per-(user,channel) `asyncio.Lock`.
- `_serialize_content()` in `file_store.py` uses direct attribute access (`getattr`) — not `model_dump()` — to avoid Pydantic MockValSer on Python 3.14.
- New tools: add schema to `core/tools.py`, handler to `core/tool_handlers/`, register in `ToolRegistry`.

## Environment Variables (.env)

| Key | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Required |
| `DISCORD_TOKEN` | Optional — Discord bot skips if unset |
| `DISCORD_ALLOWED_GUILD_IDS` | Comma-separated guild IDs (empty = all guilds) |
| `DISCORD_ACTIVE_CHANNEL_IDS` | Channels where Trixxie responds without @mention |
| `SL_BRIDGE_SECRET` | Optional shared secret — must match `SECRET` in LSL script |
| `SL_BRIDGE_PORT` | Default 8080 |
| `SEARCH_PROVIDER` | `brave` or `serper` |
| `SEARCH_API_KEY` | Brave or Serper key |
| `MEMORY_MAX_HISTORY` | Turns kept per conversation file (default 20) |

## Do Not

- Do not use `model_dump()` on Anthropic SDK response objects
- Do not add synchronous HTTP calls inside async handlers
- Do not commit `.env`, `.venv/`, or `data/memory/` (all gitignored)
- Do not reintroduce LSO memory workarounds (AV_MAX<25, message caps, loop candidate caps)
