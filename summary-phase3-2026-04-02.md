# Trixxie Carissa — Phase 3 Build Summary
**Dates:** 2026-04-02 — 2026-04-04

---

## What Was Built

Phase 3 addressed a Discord participation bug, added active-channel configuration, implemented OpenSimulator compatibility, established Claude Code project configuration, and delivered the first viewer-native IM interface: a Cool VL Viewer Lua automation script that gives Trixxie a full private IM loop with typing indicator — no `/42` channel command required.

---

## Discord Active Channel Participation

### Problem

Trixxie was not responding to messages in server channels (e.g. `#general`) unless @mentioned. She responded correctly to DMs and @mentions everywhere. The bot code explicitly gated guild messages on `self.user in message.mentions`, so all non-mention server messages were silently dropped.

The gateway log confirmed: `mentions: []` on every regular channel message — the check was working as written, but it was too restrictive.

### Fix

Added `DISCORD_ACTIVE_CHANNEL_IDS` — a comma-separated list of channel IDs where Trixxie participates as a full member without requiring an @mention.

**`config/settings.py`** — new field:
```python
discord_active_channel_ids: list[int]  # channels where Trixxie responds without @mention
```

Loaded from `.env`:
```python
discord_active_channel_ids=[
    int(c.strip())
    for c in os.getenv("DISCORD_ACTIVE_CHANNEL_IDS", "").split(",")
    if c.strip()
],
```

**`interfaces/discord_bot/bot.py`** — updated gate logic:
```python
is_dm = isinstance(message.channel, discord.DMChannel)
is_mentioned = self.user in message.mentions
is_active_channel = message.channel.id in self._settings.discord_active_channel_ids

if not is_dm and not is_mentioned and not is_active_channel:
    return
```

**`.env` configuration:**
```
DISCORD_ACTIVE_CHANNEL_IDS=1485761920270209026
```

Multiple channels are comma-separated. Empty means Trixxie only responds to @mentions and DMs (original behavior).

---

## Cool VL Viewer — Lua Automation Script

A viewer-native IM interface built on Cool VL Viewer's Lua scripting API. Tested and working as of 2026-04-04.

### How It Works

| Step | Detail |
|---|---|
| Someone sends Trixxie a private IM | `OnInstantMsg` fires (`type == 0`, peer-to-peer only) |
| | `SetAgentTyping(true)` — typing indicator appears immediately |
| | `PostHTTP` fires an async POST to `/sl/message` |
| Claude returns a reply | `OnHTTPReply` fires |
| | `SetAgentTyping(false)` — indicator clears |
| | Reply is split into ≤1000-char chunks at sentence boundaries, delivered via `SendIM` |
| Avatar speaks in local chat | `OnReceivedChat` appends to a 10-line rolling `nearby_chat` buffer |
| | Buffer is included as context in the next IM POST |

The typing indicator is visible for exactly the duration of Claude's inference — the same natural feel as a human composing a reply.

### Key API Calls

| Function | Purpose |
|---|---|
| `OnInstantMsg(session_id, origin_id, type, name, text)` | Fires on every received IM — `type == 0` for peer-to-peer |
| `SetAgentTyping([true\|false])` | Shows/hides the typing indicator in the IM window |
| `PostHTTP(url, body, timeout, accept, content_type)` | Async HTTP POST — returns handle; fires `OnHTTPReply` on completion |
| `OnHTTPReply(handle, success, reply)` | HTTP response callback — correlates `handle → session_id` via `pending_ims` table |
| `SendIM(session_id, text)` | Delivers reply directly into the IM session |
| `OnReceivedChat(type, from_id, is_avatar, name, text)` | Local chat events — `type == 1` for normal avatar speech |
| `EncodeJSON(table)` / `DecodeJSON(string)` | Built-in JSON — handles escaping automatically |
| `GetAgentInfo()["id"]` | Own avatar UUID — used to filter Trixxie's own outbound IMs |
| `GetGridSimAndPos()["region"]` | Current region name — included in every POST body |

### Architecture Notes

- `PostHTTP` has no custom header support — secret is sent in the JSON body (`"secret"` field) rather than the `X-SL-Secret` header used by the LSL HUD. Both paths are accepted by the server.
- `pending_ims = {}` maps `handle → {session_id, origin_id}` so `OnHTTPReply` knows where to route the reply.
- `nearby_chat` starts as an empty Lua table `{}`. When empty, `EncodeJSON` serializes it as `{}` (JSON object), which fails Pydantic's `list[str]` validation. Fix: only include `nearby_chat` in the payload when it has entries — the server defaults to `[]` when absent.
- The HUD's sensor role (avatars, environment, objects, clothing) is retained. The Lua script replaces only the conversation path.

### Server-Side Change

**`interfaces/sl_bridge/server.py`** — body-based secret as fallback:

```python
class SLInboundPayload(BaseModel):
    ...
    secret: str = ""   # body-based auth for clients that cannot send custom headers
```

```python
header_secret = request.headers.get("X-SL-Secret", "")
secret = header_secret or payload.secret
```

LSL HUD continues to use `X-SL-Secret`. Lua script sends `"secret"` in the body. Both work.

### Files Created

```
lua/trixxie_companion.lua    Automation script — copy to user_settings/automation.lua
lua/README.md                Setup instructions and comparison table vs LSL HUD
```

---

## Planned: Radegast C# Plugin

Hooks into Radegast's native IM event system directly. Same `/sl/message` endpoint. More complex — requires a C# build pipeline outside the current Python+LSL stack. Planned after the Lua script is validated in the field.

---

## Claude Code Configuration

### `CLAUDE.md` (project-level)

Created `CLAUDE.md` at the project root. Loaded by Claude Code at the start of every session, giving instant context on:
- Run commands
- Key file map
- Architecture summary
- Platform rules and user ID namespacing
- Memory layout and consolidation behavior
- LSL script constraints (Mono, json_s rules, avatar cap, chunking)
- Python conventions (AsyncAnthropic, asyncio.Lock, MockValSer workaround)
- All environment variables
- Explicit "Do Not" list

### `~/.claude/CLAUDE.md` (user-level)

Created user-level preferences that apply across all projects:
- Response style: concise, no preamble, no trailing summaries, markdown links for files
- Code style: edit over create, no gratuitous additions, match existing conventions
- Git: new commits only, staged by name, confirm before destructive operations, never push uninstructed

---

## OpenSimulator Compatibility

### Research Findings

OpenSimulator (0.9.3.0, Nov 2024) is actively maintained and runs on .NET 8 / Mono. Its scripting language (OSSL) is a strict superset of SL LSL — 99% of SL scripts work without modification. XEngine was removed in 0.9.3.0; YEngine is now the only script engine.

Every LSL function in `companion_bridge.lsl` is supported in current OpenSim:

| Function | Status |
|---|---|
| `llHTTPRequest` / `http_response` | Supported |
| `llGetAgentList(AGENT_LIST_REGION, [])` | Supported |
| `llGetObjectDetails`, `llGetParcelDetails` | Supported |
| `llReplaceSubString` | Added Jan 2023 — available in all current versions |
| `llJsonGetValue` / `JSON_INVALID` | Supported in YEngine |
| `llInstantMessage`, `llDialog`, `llSensor` | Fully supported |
| `llGetEnv("time_of_day")`, `llGetEnv("sun_altitude")` | Supported — values may differ under EEP environment system |
| `HTTP_CUSTOM_HEADER`, `HTTP_VERIFY_CERT` | Supported — cloudflared HTTPS cert satisfies verification |

**The one real issue:** OpenSim's default `llHTTPRequest` response body limit is **2048 bytes** (SL's is 16384). A 4000-char reply would blow past this and be silently truncated.

### Fix — Grid-Aware Reply Cap

**`lsl/companion_bridge.lsl`** — one new config constant:
```lsl
string  GRID = "sl";   // "sl" for Second Life, "opensim" for OpenSimulator
```

Included in every `/sl/message` POST body:
```lsl
+ "\"grid\":\"" + GRID + "\","
```

**`interfaces/sl_bridge/server.py`** — new field on `SLInboundPayload`:
```python
grid: str = "sl"   # "sl" or "opensim" — controls reply size cap
```

Passed to `cap_reply()`:
```python
reply=cap_reply(result.text, grid=payload.grid),
```

**`interfaces/sl_bridge/formatters.py`** — grid-aware cap:
```python
OPENSIM_REPLY_CAP = 1800   # leaves room for JSON envelope inside 2048-byte limit

def cap_reply(text: str, grid: str = "sl") -> str:
    text = text.translate(_UNICODE_MAP)
    cap = OPENSIM_REPLY_CAP if grid == "opensim" else REPLY_HARD_CAP
    if len(text) > cap:
        text = text[:cap]
    return text
```

OpenSim admins who set `HttpBodyMaxLenMAX = 16384` in `OpenSim.ini` can use `GRID = "sl"` for full-length replies.

### Target Grids

- **OSGrid** — largest free public OpenSim grid
- **Metropolis** — European grid (~1.50€/month)
- **Standalone** — single-machine private deployments (most common personal use case)

No LSL differences exist between grids — grid-specific configuration (threat levels, OSSL permissions) is an admin concern, not a scripting concern.

---

## Files Changed

```
config/settings.py                    + discord_active_channel_ids field and loader
interfaces/discord_bot/bot.py         + is_active_channel check in on_message()
lsl/companion_bridge.lsl              + GRID config constant; included in /sl/message POST body
interfaces/sl_bridge/server.py        + grid field on SLInboundPayload; passed to cap_reply()
                                      + secret field on SLInboundPayload; body-auth fallback for Lua
interfaces/sl_bridge/formatters.py    + OPENSIM_REPLY_CAP = 1800; cap_reply() is now grid-aware
lua/trixxie_companion.lua             NEW — Cool VL Viewer automation script (full IM loop)
lua/README.md                         NEW — Setup instructions for Lua interface
CLAUDE.md                             NEW — Claude Code project instructions
~/.claude/CLAUDE.md                   NEW — Claude Code user-level preferences
lsl/ARCHITECTURE.md                   + OpenSim compatibility section; stale chat filter table removed
README.md                             + Active channel config; OpenSimulator Setup section; Lua interface; future upgrades
ARCHITECTURE.md                       Updated — Lua interface in diagram, platform table, SL flow, constraints
summary-phase3-2026-04-02.md          This file
```

---

## Phase 4 Candidates

| Area | Notes |
|---|---|
| Radegast C# plugin | Native IM loop for Radegast viewer; second optional interface after Lua validates in the field |
| Wizard-style user setup | Guided first-run configuration for non-technical users |
| Named cloudflare tunnel | Permanent subdomain — `SERVER_URL` in LSL never changes on restart |
| Vector memory | Swap `FileMemoryStore` → `ChromaMemoryStore`; one-line change in `main.py` |
| Public repo release | Scrub `SECRET` + `SERVER_URL` from LSL, replace `person_map.json` with documented placeholder, add LICENSE |
