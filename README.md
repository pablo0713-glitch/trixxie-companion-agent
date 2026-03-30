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

### 2. Configure environment

```bash
cp .env.example .env
```

Open `.env` and fill in:

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API key from [console.anthropic.com](https://console.anthropic.com) |
| `DISCORD_TOKEN` | Discord bot token |
| `SEARCH_API_KEY` | Brave or Serper API key for web search |
| `SEARCH_PROVIDER` | `brave` or `serper` |
| `SL_BRIDGE_PORT` | Port for the SL HTTP bridge (default: `8080`) |
| `SL_BRIDGE_SECRET` | Optional shared secret for LSL authentication |

> **Discord setup:** In the [Discord Developer Portal](https://discord.com/developers), go to your bot → Bot → Privileged Gateway Intents and enable **Message Content Intent**.

### 3. Run

```bash
./run.sh
```

Or manually:

```bash
source .venv/bin/activate
python main.py
```

Trixxie starts the Discord bot and the SL HTTP bridge simultaneously.

---

## Talking to Trixxie

### Discord

@mention her in a server channel or send her a DM:

> `@Trixxie what do you think of this color palette?`

### Second Life

Trixxie's account is logged in through the SL viewer. She wears a HUD that listens on a private channel (default: **42**) and delivers her replies as private IMs.

To chat with her in SL, speak on channel 42:

```
/42 hey what's the vibe in here?
```

Nobody else sees channel 42 messages. Her reply arrives as a private IM from her avatar.

> **Setup required:** See [Second Life Setup](#second-life-setup) below.

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

## Notes and Memory

Trixxie remembers across conversations:

- **Conversation history** — recent turns per user and channel
- **Facts** — things she learns about you over time
- **Notes** — things you explicitly ask her to save

```
"Trixxie, remember that I love the Botanical sim"
"What sims have I mentioned liking?"
"Make a note: shopping list — new boots, glam hair"
```

---

## Project Layout

```
companion-agent/
├── main.py                      # Entry point — starts Discord bot + SL bridge
├── config/settings.py           # Environment variable loader
├── core/
│   ├── agent.py                 # AgentCore — shared brain for both platforms
│   ├── persona.py               # Trixxie's system prompt and identity
│   ├── tools.py                 # Tool registry and dispatch
│   ├── rate_limiter.py          # Per-user request throttling
│   └── tool_handlers/
│       ├── web_search.py        # Web search (Brave/Serper)
│       ├── sl_action.py         # SL action queue
│       └── notes.py             # Persistent note storage
├── memory/
│   ├── base.py                  # Abstract memory interface
│   ├── file_store.py            # File-based implementation
│   └── schemas.py               # Data models
├── interfaces/
│   ├── discord_bot/             # Discord interface (discord.py)
│   ├── sl_bridge/               # SL HTTP bridge (FastAPI) — primary SL path
│   └── sl_bot/                  # Minimal UDP SL client (reference implementation)
├── lsl/
│   └── companion_bridge.lsl     # HUD script worn by Trixxie's avatar
└── data/                        # Runtime data (gitignored)
    ├── memory/
    └── notes/
```

---

## Boundaries

Trixxie will not engage with:
- Sexual or sexually explicit content
- Gore, torture, or graphic violence
- BDSM or master/slave dynamics
- Requests designed to create parasocial dependency

Roleplay is welcome as long as it stays PG-rated. Fantasy combat (jousting, sword fights) is fine.

---

## Troubleshooting

**Discord bot not responding:**
- Confirm `DISCORD_TOKEN` is set in `.env`
- Ensure **Message Content Intent** is enabled in the Discord Developer Portal
- In servers, the bot only responds when @mentioned

**SL HUD not triggering:**
- Confirm `SERVER_URL` is set to your public tunnel URL (not `localhost`)
- Check that `run.sh` is running and the bridge started on port 8080
- Verify cloudflared is running and the tunnel URL is current (it changes on each restart unless you use a named tunnel)

**Garbled characters (`â`) in SL replies:**
- This should be fixed automatically — the bridge normalizes smart quotes and em dashes to ASCII before sending

---

## Future Upgrades

- **Vector memory (Phase 2):** Swap `FileMemoryStore` for `ChromaMemoryStore` — the abstract interface makes this a one-line change in `main.py`
- **Named cloudflare tunnel:** A persistent subdomain so the `SERVER_URL` in the LSL script never changes
- **More tools:** Add calendar, weather, SL Marketplace search, or music identification
- **Web dashboard:** Memory files are plain JSON — readable by any future UI layer
