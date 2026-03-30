# Trixxie Carissa — Sensory Companion HUD

An LSL HUD script for Second Life that gives Trixxie continuous environmental awareness by streaming sensor data to an external AI bridge server. Trixxie can see who is nearby, what is being said around her, what the environment looks like, and what objects and attachments are present — all in real time.

---

## Requirements

- A Second Life account with the ability to attach HUD objects
- A running instance of the companion bridge server (see the server-side `README`)
- A publicly accessible HTTPS URL for the bridge (e.g. via Cloudflare Tunnel)

---

## Setup

1. Open [companion_bridge.lsl](companion_bridge.lsl) and set the two config values at the top:

   ```lsl
   string SERVER_URL = "https://your-tunnel.trycloudflare.com";
   string SECRET     = "your_secret_here";   // leave "" to disable auth
   ```

   `SECRET` must match `SL_BRIDGE_SECRET` in the server's `.env` file.

2. Create a new object in Second Life, paste the script inside it, and attach it to Trixxie as a HUD (any HUD attachment point works).

3. The HUD announces `Trixxie Sensory HUD active` in local owner-only chat when it is ready. An initial environment scan is sent to the server immediately on attach.

---

## Usage

**Touch the HUD** to open the control menu. A dialog appears with the following options:

| Button | Action |
|---|---|
| Avatars | Toggle avatar proximity scanning on/off |
| Chat | Toggle local chat forwarding on/off |
| Environment | Toggle environment scanning on/off |
| Objects | Toggle nearby object scanning on/off |
| Scan Target | Scan the nearest avatar's worn attachments |
| Chat Filter | Switch between *DJ/Objects only* and *All Chat* |
| Status | Print current HUD settings to local chat |
| Close | Dismiss the dialog |

**Talk to Trixxie** on channel 42 by prefixing your message with `/42`:

```
/42 Hey Trixxie, what's the vibe in here?
```

The HUD forwards your message plus a rolling buffer of the last 10 local chat lines to the bridge server, and delivers Trixxie's reply back to you via instant message.

---

## Sensor Behaviour

| Sensor | Default | How often |
|---|---|---|
| Environment | ON | On attach, on region change |
| Avatars | ON | Every 150 s (5 timer ticks × 30 s) |
| Chat | ON | On every chat event matching the filter |
| Objects | OFF | On region change (if enabled), on toggle |

**Chat buffer:** the HUD keeps a rolling window of the last **10** local chat lines. All 10 are attached to every `/42` message as ambient context for Trixxie — the server uses the full 10.

**Chat filter modes:**
- *DJ/Objects only* (default) — forwards only messages from non-avatar sources (stream announcers, DJ bots, scripted objects)
- *All Chat* — forwards every message heard on channel 0

**Avatar scanning:** always scans the full region via `llGetAgentList` and returns the **25 closest avatars** to Trixxie, sorted by distance. The list is capped at 25 regardless of how many avatars are present in the sim — this keeps memory usage stable and prevents stack-heap collisions in crowded regions (up to 100 avatars).

---

## Security

If `SECRET` is set, every outbound HTTP request includes the header:

```
X-SL-Secret: <your secret>
```

The bridge server should reject requests that do not present this header.

---

## Channels

| Channel | Purpose |
|---|---|
| `0` | Local chat monitoring (listen-only) |
| `42` | Conversation with Trixxie |
| `-7654321` | Internal HUD dialog responses (owner-only) |
