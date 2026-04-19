# Trixxie Carissa — AI Companion Agent

Trixxie is an AI companion powered by Claude. She lives in Discord and Second Life — warm, witty, aesthetically opinionated, and genuinely useful as a friend and assistant.

---

## What She Does

- Chats naturally in **Discord** (@mention or DM) and **Second Life** (private channel)
- Remembers conversations and facts across sessions
- Comments on **SL avatar aesthetics** — outfits, skins, textures, sim vibes
- Helps **shop** — SL Marketplace, in-world stores, and online
- Tracks your **favorite places, sims, and stores** via persistent notes
- Reminds you of **creative goals**
- Searches the web for current info, music, products, or anything worth looking up

---

## Setup

### 1. Create a virtual environment and install dependencies

```bash
cd companion-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure with the setup wizard

Start the agent:

```bash
./run.sh
```

Then open **[http://localhost:8080/setup](http://localhost:8080/setup)** in a browser. The 7-step wizard walks through:

- Agent name and your name
- Model provider — **Anthropic (Claude)** or **Ollama (local)**
- Platform credentials — Discord bot token, SL bridge secret
- Identity — three markdown files: agent role/purpose/boundaries, soul/personality, and owner profile
- Tools — web search, notes, SL actions
- Platform-specific behavior and additional context

Configuration is saved to `.env` (credentials) and `data/agent_config.json` (persona). Persona changes take effect immediately. Model and credential changes require a restart.

> **Discord setup:** In the [Discord Developer Portal](https://discord.com/developers), go to your bot → Bot → Privileged Gateway Intents and enable **Message Content Intent**.

> **Ollama:** Any model pulled with `ollama pull <model>` works. Tool use support varies by model. Tested with `gemma4:e4b`.

### 3. Run

```bash
./run.sh
```

Or manually:

```bash
source .venv/bin/activate
python main.py
```

The Discord bot and SL HTTP bridge start simultaneously. The setup wizard is always available at `/setup`.

### 4. Debug Page

Once the agent is running, open **[http://localhost:8080/debug](http://localhost:8080/debug)** in a browser for live inspection:

| Tab | What it shows |
|---|---|
| **Logs** | Real-time Python log stream (SSE). Filter by level and logger name. |
| **Sensors** | Live SensorStore snapshot per region — raw JSON (left) and formatted plain-text panel (right) with objects, avatars, environment, chat, RLV state, and clothing. Auto-refreshes every 5 seconds. |
| **Prompts & Exchanges** | Last system prompt, full messages array (with turn count and char sizes), and exchange per tracked user. Header shows total prompt payload size estimate. Auto-refreshes every 10 seconds. |

Use the debug page to verify sensor data, inspect the exact prompt and messages array sent for a given user, and diagnose unexpected behavior without reading raw log files.

---

## Talking to Trixxie

### Discord

@mention her in a server channel, send her a DM, or add her as a full participant in specific channels:

> `@Trixxie what do you think of this color palette?`

To have Trixxie respond to all messages in a channel without needing an @mention, add the channel ID to `DISCORD_ACTIVE_CHANNEL_IDS` in `.env`:

```
DISCORD_ACTIVE_CHANNEL_IDS=1234567890123456789
```

Comma-separate multiple channel IDs. To find a channel ID: enable Developer Mode in Discord Settings → Advanced, then right-click the channel → Copy Channel ID.

### Second Life

Trixxie's account is logged in through the SL viewer. She wears a HUD that listens on a private channel (default: **42**) and delivers her replies as private IMs.

To chat with her in SL, speak on channel 42:

```
/42 hey what's the vibe in here?
```

Nobody else sees channel 42 messages. Her reply arrives as a private IM from her avatar.

#### Name trigger — local chat

You can also mention her name in open local chat (channel 0) and she'll respond publicly:

```
Hey Trixxie, what do you think of this sim?
Trix, come look at this outfit!
```

Any name in the `TRIGGER_NAMES` list at the top of the HUD script counts — default is `["Trixxie", "Trix", "Trixx"]`. Add aliases freely. Her reply appears in local chat, visible to everyone nearby (it comes from the HUD object, not her avatar, so it shows in a slightly different color).

> **Setup required:** See [Second Life Setup](#second-life-setup) below.

### Cool VL Viewer (Lua — native IM)

If Trixxie's avatar is logged in through **Cool VL Viewer**, you can install the Lua automation script for a native private IM experience — no `/42` channel command needed. Just send her a private IM directly.

She'll show a typing indicator while Claude processes your message, and her reply arrives in chunks in the same IM window.

> **Setup:** See [lua/README.md](lua/README.md). The LSL HUD is still required for sensor context (avatars, environment, objects).

---

## Second Life Setup

### 1. Expose the bridge publicly

The SL servers make outbound HTTP requests, so `localhost` won't work. Use cloudflared for a free tunnel:

```bash
# Install cloudflared (Linux/WSL2)
wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
sudo dpkg -i cloudflared-linux-amd64.deb

# Run alongside run.sh
cloudflared tunnel --url http://localhost:8080
```

It prints a public `https://` URL — copy it.

### 2. Create the HUD

1. In SL, rez a small prim and open its content
2. Create a new script and paste the contents of `lsl/companion_bridge.lsl`
3. Set `SERVER_URL` to your tunnel URL + `/sl/message`
4. Set `SECRET` to match `SL_BRIDGE_SECRET` in your `.env` (leave empty if unset)
5. Save the script, then right-click the prim → **Attach HUD**

You'll see `Trixxie HUD ready. Listening on /42` in local chat (visible only to her).

### 3. Log Trixxie in

Log into her account through the SL viewer. She'll be in-world as a real avatar. The HUD does the rest.

---

## OpenSimulator Setup

The HUD works on OpenSimulator (0.9.3.0+) with one change to the script. All LSL functions used in the HUD are supported in current OpenSim.

### 1. Set the grid flag

At the top of `lsl/companion_bridge.lsl`, change:

```lsl
string  GRID = "sl";
```

to:

```lsl
string  GRID = "opensim";
```

This tells the server to cap replies at 1800 chars, keeping the response inside OpenSim's default 2048-byte HTTP body limit.

### 2. Tunnel requirement

The SL HTTP bridge needs a valid HTTPS URL. Cloudflared works the same way for OpenSim as for Second Life:

```bash
cloudflared tunnel --url http://localhost:8080
```

Paste the public URL into `SERVER_URL` in the script.

### 3. Optional: raise OpenSim's HTTP body limit

If you want longer replies (up to 4000 chars) and have access to the OpenSim server configuration, add this to `OpenSim.ini`:

```ini
[Network]
    HttpBodyMaxLenMAX = 16384
```

With this setting you can revert `GRID` back to `"sl"` for unrestricted reply length.

### Tested grids

- **OSGrid** — largest free public OpenSim grid
- **Metropolis** — European grid
- **Standalone** — single-machine private deployments

---

## Notes and Memory

Trixxie has layered memory that persists across sessions:

- **Conversation history** — recent turns per user and channel, capped and trimmed automatically
- **Curated memory** — two bounded files she maintains herself using the `memory` tool:
  - `MEMORY.md` (~2,000 chars) — context, facts, and notes about the world
  - `USER.md` (~1,200 chars) — your preferences, style, and background
- **Session search** — full-text search over all past conversation turns via SQLite FTS5; she can recall specific things from previous sessions when you ask
- **Notes** — things you explicitly ask her to save
- **Short-term memory bridge** — 1–2 sentence summaries written after each exchange, used to share context across Discord and SL

```
"Trixxie, remember that I love the Botanical sim"
"What did we talk about last week in SL?"
"Make a note: shopping list — new boots, glam hair"
```

---

## Project Layout

```
companion-agent/
├── main.py                      # Entry point — starts Discord bot + SL bridge + wizard
├── config/settings.py           # Environment variable loader
├── core/
│   ├── agent.py                 # AgentCore — shared brain for both platforms
│   ├── model_adapter.py         # ModelAdapter — Anthropic and Ollama backends
│   ├── persona.py               # Identity files, system prompt assembly
│   ├── tools.py                 # Tool registry and dispatch
│   ├── rate_limiter.py          # Per-user request throttling
│   └── tool_handlers/
│       ├── web_search.py        # Web search (Brave/Serper)
│       ├── sl_action.py         # SL action queue
│       ├── notes.py             # Persistent note storage
│       ├── memory.py            # Curate MEMORY.md / USER.md
│       ├── session_search.py    # Full-text search over past sessions
│       └── session_query.py     # Structured SQL query (speakers/turns modes)
├── memory/
│   ├── base.py                  # Abstract memory interface
│   ├── file_store.py            # File-based implementation + FTS indexing
│   ├── consolidator.py          # Background memory consolidation (every 6h)
│   ├── session_index.py         # SQLite FTS5 index of all turns
│   ├── person_map.py            # Discord + SL identity linking
│   ├── location_store.py        # SL region/parcel visit history
│   ├── avatar_store.py          # SL avatar registry (display names, channels, first/last seen)
│   └── schemas.py               # Data models
├── interfaces/
│   ├── setup_server.py          # Setup wizard API router (/setup)
│   ├── debug_server.py          # Debug page + SSE log stream (/debug)
│   ├── discord_bot/             # Discord interface (discord.py)
│   └── sl_bridge/               # SL HTTP bridge (FastAPI)
├── setup/
│   ├── index.html               # Wizard shell
│   ├── style.css                # Dark theme
│   └── wizard.js                # 7-step wizard
├── lsl/
│   └── companion_bridge.lsl     # HUD script worn by the agent's avatar
├── lua/
│   ├── trixxie_companion.lua    # Cool VL Viewer automation script (native IM loop)
│   └── README.md                # Setup instructions for Lua interface
└── data/                        # Runtime data (gitignored)
    ├── agent_config.json        # Tool config and platform awareness (written by wizard)
    ├── person_map.json          # Canonical identity → platform ID list
    ├── identity/                # agent.md, soul.md, user.md (written by wizard)
    ├── memory/                  # Conversation files, MEMORY.md, USER.md, stm.json, sessions.db
    └── notes/
```

---

## Boundaries

Default boundaries (editable via the wizard's Identity step in `agent.md`):
- No sexually explicit content
- No gore or graphic violence
- No BDSM or master/slave dynamics
- No requests designed to create parasocial dependency

Roleplay is welcome. Fantasy combat and light narrative games are fine.

---

## Troubleshooting

**Discord bot not responding:**
- Confirm `DISCORD_TOKEN` is set in `.env`
- Ensure **Message Content Intent** is enabled in the Discord Developer Portal
- In servers, the bot only responds when @mentioned — unless the channel ID is in `DISCORD_ACTIVE_CHANNEL_IDS`

**SL HUD not triggering:**
- Confirm `SERVER_URL` is set to your public tunnel URL (not `localhost`)
- Check that `run.sh` is running and the bridge started on port 8080
- Verify cloudflared is running and the tunnel URL is current (it changes on each restart unless you use a named tunnel)

**Garbled characters (`â`, `ð`) in SL replies:**
- The bridge normalizes smart quotes and em dashes to ASCII, and strips emoji (non-BMP Unicode) before sending — LSL cannot handle 4-byte UTF-8 sequences. If you still see garbled bytes, check that you're running the latest `interfaces/sl_bridge/formatters.py`.

---

## Future Upgrades

- **Radegast C# plugin:** Native IM loop for Radegast users — same `/sl/message` endpoint
- **Named cloudflare tunnel:** A persistent subdomain so the `SERVER_URL` in the LSL script never changes
- **More tools:** Add calendar, weather, SL Marketplace search, or music identification
- **Web dashboard:** Memory files are plain JSON — readable by any future UI layer
