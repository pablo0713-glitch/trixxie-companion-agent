# What's in the v1.0 Release?

A quick reference for what the framework does out of the box.

---

## AI Model Support

Supports seven providers. Switch by changing one line in `.env` — no code changes needed.

| Provider | Type | Notes |
|---|---|---|
| **Anthropic (Claude)** | Cloud | Best overall quality; prompt caching reduces cost on long sessions |
| **OpenAI** | Cloud | GPT-4o and other OpenAI models |
| **Gemini** | Cloud | Google's models via OpenAI-compatible endpoint |
| **Grok** | Cloud | xAI's models |
| **OpenRouter** | Cloud | Access dozens of models through a single API key |
| **Ollama** | Local | Run open-source models on your own hardware, no API cost |
| **LM Studio** | Local | Local models via LM Studio's built-in server |

---

## Platforms

### Discord
- Responds to @mentions and DMs
- Optionally responds to all messages in designated channels without a mention
- Can be restricted to specific servers (guild IDs)

### Second Life
- Responds on private channel `/42` — replies arrive as a private IM, invisible to others
- Responds to local chat when the agent's name is spoken (configurable trigger names)
- Sensor HUD streams live context to the agent: nearby avatars, environment, ambient chat, objects, outfit
- Full reply chunking — long responses are split at sentence boundaries and delivered cleanly

### OpenSimulator
- Same HUD and bridge as Second Life
- One config line change (`string GRID = "opensim";`) caps replies at OpenSim's HTTP body limit
- Tested on OSGrid, Metropolis, and standalone deployments

---

## Memory

The agent maintains five layers of memory that persist across sessions and restarts.

| Layer | What it stores | Size limit |
|---|---|---|
| **Conversation history** | Recent turns per user/channel | Configurable (default: 20 turns) |
| **MEMORY.md** | Facts and notes the agent curates itself | ~2,000 chars |
| **USER.md** | Owner preferences, background, style | ~1,200 chars |
| **Notes** | Free-form notes saved and retrieved on request | Unlimited |
| **Session search** | Full-text index of all past turns (SQLite FTS5) | Unlimited |

Memory consolidation runs every 6 hours in the background — long histories are summarized and trimmed automatically.

---

## Tools

| Tool | What it does |
|---|---|
| **Web search** | Live results via Serper or Brave Search API |
| **Notes** | Save and retrieve named notes per user |
| **Memory read/write** | Agent can update its own MEMORY.md and USER.md |
| **Session search** | Query past conversations by date, platform, or speaker |
| **SL action** | Send IMs, emotes, local chat, trigger animations, mute/unmute avatars |
| **Outfit scan** | Trigger an RLV outfit scan and read what the avatar is wearing |

Tools are individually toggleable in the wizard.

---

## Second Life Sensors (HUD)

The LSL HUD streams live context to the agent. Each sensor is independently toggleable and works in two modes: **streaming** (posts on a timer) or **per-message** (posts when someone speaks).

| Sensor | What it captures | Streaming interval |
|---|---|---|
| **Avatars** | Nearest 25 avatars with distances | Every 60s |
| **Chat** | Rolling 10-line local chat buffer | Flushed every 90s |
| **Environment** | Sim name, parcel, time of day, rating | Every 600s |
| **Objects** | Nearby scripted and non-scripted objects | Every 300s |
| **RLV state** | Sitting, flying, autopilot, position | Every 30s |
| **My Outfit** | Attachment slots and clothing layers worn | On demand |

---

## RLV Integration

The HUD performs a `@version` handshake on attach and uses RLV for outfit scanning (`@getattach`, `@getoutfit`). The avatar also wears an OpenCollar necklace — teleport, follow, and sit/unsit commands work naturally through that system without any framework involvement.

---

## Setup Wizard

A 7-step browser-based wizard at `http://localhost:8080/setup`. Covers:

1. Agent name and owner name
2. Model provider selection and API key
3. Platform credentials (Discord token, SL bridge secret)
4. Identity files — `agent.md`, `soul.md`, `user.md` — edited in-browser
5. Tool toggles
6. Additional context and platform awareness overrides
7. Review and save

The wizard writes `.env` and `data/agent_config.json`. Persona changes are live on the next message. Model/credential changes require a server restart.

---

## Debug Page

Live visibility at `http://localhost:8080/debug`:

- **Logs** — real-time Python log stream with level and logger filtering
- **Sensors** — live sensor snapshot per region, raw JSON and formatted, auto-refreshes every 5s
- **Prompts & Exchanges** — exact system prompt and message array sent for each user, auto-refreshes every 10s

---

## Cross-Platform Identity

The agent links Discord and Second Life identities to a single canonical person. Context, memory, and facts carry across platforms for the same user.

---

## What's Not in v1.0

- **RLV movement controls** (teleport, sit, follow) — handled externally via OpenCollar
- **Voice** — stub endpoint exists; no voice model configured
- **Outfit context enrichment** — attachment names and outfit folder name via `@getstatus` and `llGetAttachedList()` — planned for v1.5
- **Debug session query UI** — browse conversation history from the browser — planned for v1.5
- **Radegast C# plugin** — third viewer interface — on the roadmap
