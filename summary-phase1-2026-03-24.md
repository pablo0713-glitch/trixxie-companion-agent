# Trixxie Carissa — Phase 1 Build Summary
**Date:** 2026-03-24

---

## What Was Built

A fully functional AI companion agent named Trixxie Carissa, powered by Claude (claude-sonnet-4-6), running simultaneously on Discord and Second Life.

---

## Core Agent

- Built `AgentCore` with a full Anthropic agentic tool loop (max 5 rounds, forced text reply on cap)
- Switched from sync `anthropic.Anthropic` to `AsyncAnthropic` — fixes event loop blocking that was causing Discord to go silent after API calls succeeded
- Fixed Python 3.14 Pydantic `MockValSer` serialization bug by extracting Anthropic SDK object fields directly via `getattr` instead of calling `model_dump()`

---

## Discord

- `TrixxieBot` responds to @mentions in servers and all DMs
- Enabled Message Content Intent in Discord Developer Portal
- Chunked replies for Discord's 2,000-char limit
- Trixxie is live and responding on Discord as **Trixxie Carissa#6316**

---

## Second Life

Worked through three SL architecture approaches before landing on the right one:

1. **Channel 42 LSL listener on StonedGrits' HUD** — rejected, user wanted true IM feel
2. **Headless UDP bot avatar** — correct for direct IMs but avatar isn't visually present in-world
3. **Trixxie logged in via SL viewer + LSL HUD worn by Trixxie** — final approach

**Final SL architecture:**
- Trixxie's account is logged into SL via the viewer — she is a real, visible avatar in-world
- She wears a HUD containing `lsl/companion_bridge.lsl`
- The HUD listens on **channel 42** for nearby chat
- StonedGrits types `/42 message` — invisible to other users
- HUD POSTs to the FastAPI bridge via cloudflared tunnel
- Claude processes the message and returns a reply
- HUD delivers the reply via `llInstantMessage` — arrives as a private IM from Trixxie

**Custom SL UDP protocol** (`interfaces/sl_bot/sl_protocol.py`):
- Written from scratch using only Python stdlib when pyogp failed on Python 3.14
- Handles: XMLRPC login, UDP circuit setup, UseCircuitCode, CompleteAgentMovement, AgentUpdate keepalive, StartPingCheck/CompletePingCheck, RegionHandshake/RegionHandshakeReply, ImprovedInstantMessage send/receive
- Kept in codebase as a reference implementation; not the active SL path

**Unicode fix:**
- SL was displaying `â` instead of smart quotes and em dashes
- Fixed by normalizing Unicode to ASCII in `interfaces/sl_bridge/formatters.py` before sending

---

## Memory and Tools

- File-based JSON memory with per-(user, channel) `asyncio.Lock` for write safety
- Conversation history, persistent facts, and named notes per user
- Tools: web search (Brave API), note write/read/list, SL action queue
- Memory namespaced by platform: `discord_{snowflake}` and `sl_{uuid}`

---

## Infrastructure

- Python 3.14 (Homebrew/linuxbrew), virtualenv at `.venv/`
- Run via `./run.sh` (activates venv, starts `main.py`)
- Discord bot + SL HTTP bridge start concurrently via `asyncio.gather()`
- SL bridge exposed publicly via **cloudflared tunnel** (required for SL servers to reach localhost)
- Logging set to DEBUG level in `main.py`

---

## Key Bugs Fixed

| Bug | Fix |
|---|---|
| `ModuleNotFoundError: anthropic` | User was running system Python; fixed with `./run.sh` activating venv |
| `PrivilegedIntentsRequired` Discord error | Enabled Message Content Intent in Discord Developer Portal |
| pyogp incompatible with Python 3.14 | Replaced with custom stdlib UDP implementation |
| `BadRequestError: credit balance too low` | Switched from Trixxie Carissa workspace to Default workspace API key |
| Every Discord message returned "Something went sideways" | Sync Anthropic client blocking asyncio event loop; fixed by switching to `AsyncAnthropic` + `await` |
| `MockValSer` Pydantic crash on memory write | Replaced `model_dump()` with direct attribute extraction in `_serialize_content()` |
| SL avatar not appearing online | Added RegionHandshakeReply and StartPingCheck/CompletePingCheck handlers to UDP protocol |
| Garbled `â` characters in SL | Added Unicode-to-ASCII normalization in SL bridge formatter |

---

## Files

```
companion-agent/
├── main.py                          Entry point — Discord bot + SL HTTP bridge
├── config/settings.py               Environment variable loader
├── core/
│   ├── agent.py                     AgentCore — shared brain, async tool loop
│   ├── persona.py                   Trixxie's system prompt and identity
│   ├── tools.py                     Tool registry and dispatch
│   ├── rate_limiter.py              Per-user token bucket rate limiting
│   └── tool_handlers/
│       ├── web_search.py            Brave/Serper web search
│       ├── sl_action.py             SL action queue
│       └── notes.py                 Persistent note storage
├── memory/
│   ├── base.py                      Abstract memory interface
│   ├── file_store.py                File-based JSON implementation
│   └── schemas.py                   Pydantic data models
├── interfaces/
│   ├── discord_bot/bot.py           Discord interface
│   ├── sl_bridge/server.py          FastAPI HTTP bridge (primary SL path)
│   ├── sl_bridge/formatters.py      SL text trimming + Unicode normalization
│   └── sl_bot/sl_protocol.py        Custom stdlib SL UDP protocol (reference)
├── lsl/companion_bridge.lsl         HUD script worn by Trixxie's avatar
├── README.md                        Setup and usage documentation
├── ARCHITECTURE.md                  Technical deep-dive
└── summary-phase1-2026-03-24.md     This file
```

---

## Phase 2 Candidates

- **Vector memory:** Swap `FileMemoryStore` for `ChromaMemoryStore` — abstract interface makes this a one-line change in `main.py`
- **Named cloudflare tunnel:** Permanent subdomain so the LSL `SERVER_URL` never needs updating
- **Identity linking:** Unify Discord and SL memory for the same person via `_identity_links.json`
- **More tools:** Calendar, weather, SL Marketplace search, music identification
- **Web dashboard:** Memory files are plain JSON — readable by any future UI layer
