# Trixxie Carissa — Cool VL Viewer Lua Interface

An alternative to the LSL HUD that uses Cool VL Viewer's native Lua scripting API. Trixxie receives private IMs directly, shows a typing indicator while Claude processes the message, and delivers the reply back into the same IM window — no `/42` chat command required.

This interface **replaces the conversation path only**. The LSL HUD is still needed for sensor data (avatars, environment, objects, clothing) and ambient chat context.

---

## Requirements

- **Cool VL Viewer** (any recent release with Lua v5.5 support)
- Trixxie's bridge server running and reachable via a public HTTPS URL (same setup as the LSL HUD)

---

## Installation

1. Copy `trixxie_companion.lua` to your Cool VL Viewer user settings folder:

   | OS | Path |
   |---|---|
   | Linux | `~/.secondlife/user_settings/automation.lua` |
   | Windows | `%APPDATA%\SecondLife\user_settings\automation.lua` |
   | macOS | `~/Library/Application Support/SecondLife/user_settings/automation.lua` |

   > If `automation.lua` already exists, append or merge the three callback functions and config block rather than replacing the file.

2. Edit the config block at the top of the file:

   ```lua
   local SERVER_URL = "https://your-tunnel.trycloudflare.com"  -- base URL, same as LSL HUD
   local SECRET     = ""       -- match SL_BRIDGE_SECRET in .env, or leave empty
   local GRID       = "sl"     -- "opensim" if running on an OpenSim grid
   ```

3. Restart Cool VL Viewer (or reload the script via **Advanced → Lua → Reload**).

---

## How It Works

| Step | What happens |
|---|---|
| Someone sends Trixxie a private IM | `OnInstantMsg` fires (type == 0, peer-to-peer only) |
| | `SetAgentTyping(true)` — typing indicator appears immediately |
| | `PostHTTP` fires an async POST to `/sl/message` |
| Claude returns a reply | `OnHTTPReply` fires |
| | `SetAgentTyping(false)` — indicator clears |
| | Reply is split into ≤ 1000-char chunks and delivered via `SendIM` |
| Avatar speaks in local chat | `OnReceivedChat` appends the line to a 10-line rolling buffer |
| | Buffer is included as `nearby_chat` context in the next IM POST |

The typing indicator is visible for exactly the duration of Claude's inference — the same natural feel as a human typing a response.

---

## Authentication

Cool VL Viewer's `PostHTTP` cannot send custom HTTP headers, so the secret is included in the JSON request body rather than in `X-SL-Secret`. The server accepts the secret from either location, so the LSL HUD and this script can coexist without any server-side changes beyond the one already made.

---

## Differences from the LSL HUD

| Feature | LSL HUD | Lua script |
|---|---|---|
| Conversation trigger | `/42 message` in local chat | Private IM to Trixxie directly |
| Sensor data (avatars, env, etc.) | Yes | No — HUD still required |
| Ambient chat buffer | Yes | Yes — `OnReceivedChat` |
| Typing indicator | No | Yes — `SetAgentTyping` |
| Reply chunking | `send_chunked()` in LSL | `split_chunks()` in Lua |
| Custom auth header | `X-SL-Secret` | Body `secret` field |

---

## Troubleshooting

**No reply arrives:**
- Confirm `SERVER_URL` is set to the correct public HTTPS URL (not localhost).
- Check that the bridge server is running (`./run.sh`) and cloudflared is active.
- In the viewer, open **Advanced → Lua → Show Lua console** and check for errors.

**"Authentication failed." reply:**
- Confirm `SECRET` in the Lua script matches `SL_BRIDGE_SECRET` in `.env`.

**Replies cut off mid-sentence:**
- The chunker breaks at sentence boundaries. If replies are still truncating, the `REPLY_HARD_CAP` on the server (4000 chars for SL, 1800 for OpenSim) may be too low for the conversation style — adjust in `interfaces/sl_bridge/formatters.py`.
