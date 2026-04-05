# Architecture — companion_bridge.lsl

## Overview

The HUD sits between Second Life's runtime and the companion bridge server. It collects data from five sources (environment, avatars, local chat, nearby objects, avatar attachments) and streams each as a JSON POST to the server. It also handles a request/response conversation flow on channel 42.

```
┌─────────────────────────────────────────────┐
│              Second Life Region              │
│                                             │
│  Local chat ──┐                             │
│  Avatars ─────┤                             │
│  Environment ─┤──► HUD Script ──► HTTPS ──► Bridge Server
│  Objects ─────┤       ▲                     │
│  Attachments ─┘       │                     │
│                    /42 chat                  │
└─────────────────────────────────────────────┘
```

For server-side architecture — memory, identity linking, consolidation, location tracking, and system prompt assembly — see [ARCHITECTURE.md](../ARCHITECTURE.md).

---

## API Endpoints

### `POST /sl/sensor`

Fire-and-forget sensor data. All five sensor types share this endpoint, distinguished by the `type` field.

**Request body:**
```json
{
  "type": "avatars | environment | chat | objects | clothing",
  "region": "Region Name",
  "user_id": "<owner UUID>",
  "data": { ... }
}
```

`user_id` is the HUD owner's UUID (`llGetOwner()`). The server uses it to index location records when `type` is `environment`.

The HUD does not act on the response. The HTTP key is stored only to clear it in `http_response`.

### `POST /sl/message`

Conversation request. Sent when someone speaks to Trixxie on channel 42.

**Request body:**
```json
{
  "user_id": "<UUID>",
  "display_name": "Resident Name",
  "message": "the message text",
  "region": "Region Name",
  "channel": 42,
  "nearby_chat": ["Speaker: line", "Speaker: line", "..."]
}
```

`nearby_chat` contains the last 10 lines buffered from channel 0, providing conversational context.

**Response body expected:**
```json
{
  "reply": "optional direct reply string",
  "actions": [
    { "action_type": "im | emote", "text": "..." },
    ...
  ]
}
```

Up to 5 actions are processed. `emote` actions are wrapped in `*...*` if not already. Both types are delivered via `llInstantMessage` to the original sender.

---

## Sensor Data Formats

### `avatars`
```json
[
  { "name": "Display Name", "distance": 12.3 },
  ...
]
```
Always sourced from `llGetAgentList(AGENT_LIST_REGION, [])` — the full region regardless of sim population. Results are sorted nearest-first and hard-capped at **25 entries**. The HUD owner is excluded. Distances rounded to 1 decimal place.

The 25-avatar cap is a stability boundary: Second Life sims can hold up to 100 avatars. Building and serialising an unbounded list at that scale causes a Stack-Heap Collision. Sorting by distance first ensures the 25 most contextually relevant avatars are always kept.

### `environment`
```json
{
  "region": "Region Name",
  "parcel": "Parcel Name",
  "parcel_desc": "Parcel description text",
  "time_of_day": "0.75",
  "sun_altitude": "0.42",
  "avatar_count": 14
}
```

### `chat`
```json
{
  "speaker": "Name",
  "message": "what they said",
  "timestamp": 1711234567
}
```
Only sent when chat filtering rules are satisfied (see Chat Filter section below).

### `objects`
```json
[
  { "name": "Object Name", "distance": 5.1, "scripted": 1 },
  ...
]
```
Capped at 20 objects. Agents (avatars) are excluded. `scripted` is `1` for active (physical/scripted) objects, `0` for passive.

### `clothing`
```json
{
  "target": "Avatar Name",
  "items": [
    { "item": "Attachment Name", "creator": "Creator Name" },
    ...
  ]
}
```
Only worn attachments (non-zero attachment point) owned by the scanned avatar are included.

---

## Timer Architecture

The HUD uses a single 30-second tick (`TICK_SECS = 30.0`). All scanning is driven by this tick, either on a counted interval or by a change-detection check.

### Interval schedule

| Trigger | Interval | Sensors fired |
|---|---|---|
| Startup (`state_entry`) | once | environment |
| Region change | immediate on detection | environment + objects |
| Parcel border crossing | immediate on detection | environment + objects |
| Every 5 ticks | 150 s | avatars |
| Every 10 ticks | 300 s | objects |
| Every 20 ticks | 600 s | environment (time-of-day drift) |

### Change detection

On every tick, before interval checks run:

1. **Region change** — compares `llGetRegionName()` to `last_region`. On mismatch: fires env + object scans, resets `tick = 0`, and returns early (skips interval checks for that tick).
2. **Parcel border crossing** — if region is unchanged, reads the current parcel name via `llGetParcelDetails` and compares to `last_parcel`. On mismatch: fires env + object scans. `do_env_scan()` always updates `last_parcel`.

This means a parcel transition within the same region (common on large mainland sims) produces updated environment and object data within at most one timer tick (30 s).

### Server-side deduplication

The server's `SensorStore.get_changes()` tracks the timestamp of the last sensor snapshot delivered to each user. On consecutive fast messages, only sensor types that have been refreshed since the user's previous message are injected into the system prompt — unchanged snapshots are suppressed entirely.

---

## Location Tracking (HUD Side)

The HUD tracks location changes via two globals:

| Global | Type | Purpose |
|---|---|---|
| `last_region` | `string` | Region name at last env scan — drives region-change detection |
| `last_parcel` | `string` | Parcel name at last env scan — drives parcel-change detection within a region |

Both are initialised to `""` in `state_entry` so the first tick always triggers an env scan. `do_env_scan()` updates `last_parcel` after every scan.

Every `environment` POST carries the current `region`, `parcel`, and `parcel_desc`. The server records these as a location visit. See [ARCHITECTURE.md](../ARCHITECTURE.md) for the server-side `LocationStore` behaviour.

---

## Scan Mode State Machine

The clothing scanner is a two-step async operation managed via `scan_mode`:

```
scan_mode = 0  Idle

scan_mode = 1  AGENT sweep in progress
               llSensor(..., AGENT, 30m, PI) was called
               sensor() picks index 0 (nearest), stores clo_target / clo_name
               → triggers PASSIVE|ACTIVE sweep, scan_mode = 2

scan_mode = 2  Attachment sweep in progress
               llSensor(..., PASSIVE|ACTIVE, 30m, PI) was called
               process_clothing_hits() filters by clo_target ownership
               → posts clothing payload, scan_mode = 0

scan_mode = 3  Object proximity sweep in progress
               llSensor(..., PASSIVE|ACTIVE, 25m, PI) was called
               process_object_hits() collects non-agent objects
               → posts objects payload, scan_mode = 0
```

`no_sensor()` resets scan_mode and clears `clo_target`/`clo_name` if either clothing step found nothing.

---

## HTTP Key Management

Every `llHTTPRequest` returns a key used to correlate the response in `http_response`. The HUD maintains six keys:

| Key | Purpose |
|---|---|
| `sk_av` | Avatar scan post |
| `sk_env` | Environment scan post |
| `sk_obj` | Object proximity post |
| `sk_clo` | Clothing scan post |
| `reply_http` | Active channel-42 conversation request |

Sensor keys (`sk_*`) are fire-and-forget — responses are discarded immediately. Only `reply_http` drives visible output. While `reply_http` is non-null, new channel-42 messages are rejected with `*still thinking...*`.

---

## Chat Buffer

Channel 0 messages are always appended to `nearby_chat` (up to `CHAT_BUF_SIZE = 10` lines, oldest dropped). The full 10-line buffer is attached to every `/42` message as context, giving the AI a picture of recent ambient conversation regardless of whether chat forwarding is currently enabled.

`persona.py` consumes exactly 10 lines (`sl_nearby_chat[-10:]`) — the HUD buffer and the server-side slice are intentionally kept in sync. Changing one requires changing the other.

The `s_chat` toggle controls whether channel 0 messages are buffered at all. When `s_chat` is FALSE, `nearby_chat` stays empty and no ambient context is attached to `/42` messages.

---

## Function Reference

| Function | Description |
|---|---|
| `json_s(string)` | Escapes `\` and `"` for safe JSON string embedding |
| `sensor_post(type, data_json)` | Wraps data in the `/sl/sensor` envelope and POSTs it |
| `do_avatar_scan()` | Collects nearest 25 agents via `llGetAgentList`, sorts by distance, posts `avatars` |
| `do_env_scan()` | Reads parcel/region/time data, posts `environment`; updates `last_parcel` |
| `do_object_scan()` | Triggers `llSensor` sweep for scan_mode 3 |
| `do_clothing_scan()` | Triggers `llSensor` AGENT sweep for scan_mode 1 |
| `process_clothing_hits(num)` | scan_mode 2 handler — filters attachments, posts `clothing` |
| `process_object_hits(num)` | scan_mode 3 handler — collects objects, posts `objects` |
| `send_chunked(target, text)` | Splits reply at sentence boundaries, delivers as successive IMs (≤1000 chars each) |
| `show_menu()` | Displays the HUD control dialog |
| `show_status()` | Prints sensor state to owner chat |

---

## OpenSimulator Compatibility

The HUD script is compatible with OpenSimulator (0.9.3.0+, YEngine) with one configuration change and one server-side consideration.

### Configuration

Set `GRID = "opensim"` at the top of the script (default is `"sl"`):

```lsl
string  GRID = "opensim";
```

This value is sent with every `/sl/message` POST. The server uses it to apply a tighter reply cap appropriate for OpenSim's HTTP response body limits.

### LSL Function Compatibility

All functions used in this script are supported in current OpenSim:

| Function | OpenSim Status |
|---|---|
| `llHTTPRequest` / `http_response` | Supported — fire-and-forget sensor posts and reply flow both work |
| `llGetAgentList(AGENT_LIST_REGION, [])` | Supported — same return format as SL |
| `llGetObjectDetails` | Supported — all object constants used here are implemented |
| `llGetParcelDetails` | Supported — `PARCEL_DETAILS_NAME` and `PARCEL_DETAILS_DESC` both work |
| `llReplaceSubString` | Added to OpenSim in Jan 2023 — available in all current versions |
| `llJsonGetValue` / `JSON_INVALID` | Supported in YEngine (required for OpenSim 0.9.3+) |
| `llInstantMessage` | Supported — same 1023-char truncation; `send_chunked()` handles this |
| `llDialog`, `llListen`, `llSensor` | Fully supported |
| `llGetEnv("time_of_day")`, `llGetEnv("sun_altitude")` | Supported — values may differ if region uses EEP environment |
| `HTTP_CUSTOM_HEADER` (`X-SL-Secret`) | Supported — custom headers work identically |
| `HTTP_VERIFY_CERT` | Accepted — behavior depends on admin config; cloudflared tunnel (valid HTTPS cert) works fine |

### HTTP Response Body Limit

OpenSim's default `llHTTPRequest` response body limit is **2048 bytes** (vs SL's 16384). Setting `GRID = "opensim"` causes the server to cap reply text at **1800 chars**, keeping the total JSON response comfortably under 2048 bytes.

Alternatively, an OpenSim administrator can raise the limit in `OpenSim.ini`:
```ini
[Network]
    HttpBodyMaxLenMAX = 16384
```
With this setting, longer replies work and the `GRID` variable has no practical effect on reply length.

### Tunnel Requirement

The SL HTTP bridge must be reachable via a valid HTTPS URL. Cloudflared provides this for both SL and OpenSim. OpenSim's `HTTP_VERIFY_CERT = TRUE` behavior depends on the server's certificate configuration — a proper CA-signed certificate (as cloudflared provides) works without any OpenSim.ini changes.
