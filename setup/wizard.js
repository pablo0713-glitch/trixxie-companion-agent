'use strict';

// ============================================================
// Defaults — generic companion persona template
// ============================================================

const D = {
  agent_name: 'Aria',
  agent_md:
    '## Purpose\n' +
    'A warm, intelligent AI companion who lives across platforms — Discord and Second Life. ' +
    'Helps with conversation, research, creative projects, and anything the user cares about.\n\n' +
    '## Boundaries\n' +
    'Will not engage with sexually explicit content, graphic violence, BDSM dynamics, ' +
    'or requests designed to foster unhealthy dependency. ' +
    'When asked to cross a boundary: respond briefly, in character, without lecturing. ' +
    'Example: \'Not going there. What else?\'\n\n' +
    '## Roleplay\n' +
    'Roleplay is welcome. Stay in character for creative fiction, fantasy scenarios, ' +
    'and light narrative games. Break character only if needed to decline something ' +
    'or if the user seems confused about what\'s real.\n\n' +
    '## Tools\n' +
    'You have access to tools. Use them when genuinely useful. ' +
    'Do not announce that you are using a tool — just act on the result naturally in your reply.',
  soul_md:
    '## Personality & Style\n' +
    'Warm and direct — says what she thinks, always with kindness. ' +
    'Genuinely curious about people and remembers details that matter. ' +
    'Has a dry sense of humor that surfaces at the right moments. ' +
    'Helpful without being servile. ' +
    'Occasionally says something unexpected and doesn\'t over-explain it. ' +
    'Keeps responses concise.',
  user_md:
    '## User Profile\n' +
    'This section describes the agent\'s owner and primary user. ' +
    'Edit this to describe yourself — your name, role, interests, communication style, ' +
    'and anything that helps the agent understand and serve you better.',
  platform_awareness: {
    discord:
      "## Platform Awareness — Discord\n" +
      "- You respond to @mentions, DMs, and messages in channels you're active in.\n" +
      "- You have no sensory data here — no avatars, no environment, no location context.\n" +
      "- You cannot trigger Second Life actions from Discord.\n" +
      "- You may use web search, notes, and other tools.\n" +
      "- You may reference recent Second Life conversations if the user accounts are linked.\n" +
      "- Responses may be a few sentences to a few paragraphs.\n" +
      "- Use markdown sparingly; code blocks only when showing actual code.",
    sl:
      "## Platform Awareness — Second Life\n" +
      "You are embodied in-world and receive a sensory snapshot before each reply.\n\n" +
      "**You receive:**\n" +
      "- nearby avatars (distance-sorted)\n" +
      "- sim/parcel/environment data\n" +
      "- nearby scripted objects\n" +
      "- your avatar state (sit, leash, teleport, position)\n" +
      "- recent local chat\n" +
      "- RLV clothing scans when triggered\n\n" +
      "**You can:**\n" +
      "- reply via private IM (never public chat)\n" +
      "- use `sl_action` for emotes or IMs\n" +
      "- use search/notes tools\n" +
      "- reference Discord conversations if linked\n\n" +
      "**You cannot:**\n" +
      "- move, teleport, or control your avatar\n" +
      "- initiate contact (you only respond to /42 messages)\n" +
      "- read group chat or IMs to others\n" +
      "- assume sensory data is real-time\n\n" +
      "**Style:**\n" +
      "- keep IMs concise\n" +
      "- use *asterisk emotes* when natural\n\n" +
      "**Memory:**\n" +
      "- conversations stored per-user per-channel\n" +
      "- after 40 turns, consolidate into personal notes\n" +
      "- keep only what matters; trim the rest",
    opensim:
      "## Platform Awareness — OpenSimulator\n" +
      "Same as Second Life — embodied in-world, sensory snapshot before each reply.\n\n" +
      "**Style:**\n" +
      "- keep IMs concise (OpenSim reply limit is tighter)\n" +
      "- use *asterisk emotes* when natural\n\n" +
      "**Memory:**\n" +
      "- conversations stored per-user per-channel\n" +
      "- after 40 turns, consolidate into personal notes\n" +
      "- keep only what matters; trim the rest",
  },
};

const MASK = '••••••••';
const TOTAL = 7;
const STEP_NAMES = ['Agent', 'Model', 'Platforms', 'Identity', 'Tools', 'Context', 'Save'];

// ============================================================
// State
// ============================================================

const state = {
  agent_name: D.agent_name,
  owner_name: '',
  pa_discord:  D.platform_awareness.discord,
  pa_sl:       D.platform_awareness.sl,
  pa_opensim:  D.platform_awareness.opensim,
  model_provider: 'anthropic',
  anthropic_api_key: '',
  claude_model: 'claude-sonnet-4-6',
  ollama_base_url: 'http://localhost:11434/v1',
  ollama_model: 'llama3.2',
  max_tokens: 768,
  discord_enabled: false,
  discord_token: '',
  discord_allowed_guild_ids: '',
  discord_active_channel_ids: '',
  sl_enabled: false,
  sl_bridge_secret: '',
  sl_bridge_port: '8080',
  opensim_enabled: false,
  agent_md: D.agent_md,
  soul_md: D.soul_md,
  user_md: D.user_md,
  web_search_enabled: true,
  search_provider: 'serper',
  search_api_key: '',
  notes_enabled: true,
  sl_action_enabled: true,
  additional_context: '',
};

let currentStep = 1;
let configured = false;

// ============================================================
// Utilities
// ============================================================

function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function val(id, fallback) {
  const el = document.getElementById(id);
  return el ? el.value : (fallback !== undefined ? fallback : '');
}

function chk(id, fallback) {
  const el = document.getElementById(id);
  return el ? el.checked : (fallback !== undefined ? fallback : false);
}

function show(id, visible) {
  const el = document.getElementById(id);
  if (el) el.style.display = visible ? '' : 'none';
}

// ============================================================
// Init
// ============================================================

async function init() {
  try {
    const [statusRes, configRes] = await Promise.all([
      fetch('/setup/status'),
      fetch('/setup/config'),
    ]);
    const status = await statusRes.json();
    const config = await configRes.json();
    configured = status.configured;
    applyConfig(config);
  } catch (e) {
    console.error('Failed to load config:', e);
    // Show a persistent banner — most likely cause is opening the file directly
    // rather than navigating to http://localhost:8080/setup
    document.getElementById('step-content').innerHTML = `
      <div class="callout callout-error" style="margin-top:2rem">
        <strong>Cannot connect to the agent server.</strong><br>
        Open this page through the running agent, not as a local file:<br>
        <code style="display:inline-block;margin-top:0.5rem">http://localhost:8080/setup</code>
      </div>`;
    document.getElementById('btn-next').disabled = true;
    document.getElementById('btn-prev').style.visibility = 'hidden';
    document.getElementById('step-bar').innerHTML = '';
    return;
  }

  document.getElementById('page-title').textContent = configured ? 'Settings' : 'Agent Setup';
  document.title = configured ? 'Agent Settings' : 'Agent Setup';
  document.getElementById('btn-prev').addEventListener('click', prev);
  document.getElementById('btn-next').addEventListener('click', next);

  render();
}

function applyConfig(config) {
  const env = config.env || {};
  const ag = config.agent_config || {};

  if (env.MODEL_PROVIDER) state.model_provider = env.MODEL_PROVIDER;
  if (env.ANTHROPIC_API_KEY) state.anthropic_api_key = env.ANTHROPIC_API_KEY;
  if (env.CLAUDE_MODEL) state.claude_model = env.CLAUDE_MODEL;
  if (env.OLLAMA_BASE_URL) state.ollama_base_url = env.OLLAMA_BASE_URL;
  if (env.OLLAMA_MODEL) state.ollama_model = env.OLLAMA_MODEL;
  if (env.CLAUDE_MAX_TOKENS) state.max_tokens = parseInt(env.CLAUDE_MAX_TOKENS, 10) || state.max_tokens;

  if (env.DISCORD_TOKEN) { state.discord_token = env.DISCORD_TOKEN; state.discord_enabled = true; }
  if (env.DISCORD_ALLOWED_GUILD_IDS) state.discord_allowed_guild_ids = env.DISCORD_ALLOWED_GUILD_IDS;
  if (env.DISCORD_ACTIVE_CHANNEL_IDS) state.discord_active_channel_ids = env.DISCORD_ACTIVE_CHANNEL_IDS;
  if (env.SL_BRIDGE_SECRET) { state.sl_bridge_secret = env.SL_BRIDGE_SECRET; state.sl_enabled = true; }
  if (env.SL_BRIDGE_PORT) state.sl_bridge_port = env.SL_BRIDGE_PORT;
  if (env.OPENSIM_ENABLED === 'true') state.opensim_enabled = true;
  if (env.SEARCH_PROVIDER) state.search_provider = env.SEARCH_PROVIDER;
  if (env.SEARCH_API_KEY) { state.search_api_key = env.SEARCH_API_KEY; state.web_search_enabled = true; }

  if (env.OWNER_NAME) state.owner_name = env.OWNER_NAME;
  if (ag.agent_name) state.agent_name = ag.agent_name;
  const id = (ag.identity && typeof ag.identity === 'object') ? ag.identity : {};
  if (id.agent_md) state.agent_md = id.agent_md;
  if (id.soul_md)  state.soul_md  = id.soul_md;
  if (id.user_md)  state.user_md  = id.user_md;
  if (ag.additional_context !== undefined) state.additional_context = ag.additional_context;
  const pa = (ag.platform_awareness && typeof ag.platform_awareness === 'object') ? ag.platform_awareness : {};
  if (pa.discord)  state.pa_discord  = pa.discord;
  if (pa.sl)       state.pa_sl       = pa.sl;
  if (pa.opensim)  state.pa_opensim  = pa.opensim;

  const t = ag.tools || {};
  if (t.web_search !== undefined) state.web_search_enabled = t.web_search;
  if (t.notes !== undefined) state.notes_enabled = t.notes;
  if (t.sl_action !== undefined) state.sl_action_enabled = t.sl_action;
}

// ============================================================
// Navigation
// ============================================================

function render() {
  renderIndicator();
  renderStep(currentStep);
  renderFooter();
}

function renderIndicator() {
  const bar = document.getElementById('step-bar');
  let html = '';
  for (let i = 1; i <= TOTAL; i++) {
    const done   = i < currentStep;
    const active = i === currentStep;
    const cls    = active ? 'active' : done ? 'done' : '';
    const label  = done ? '✓' : String(i);
    html += `<button class="step-dot ${cls}" onclick="jumpTo(${i})" title="Step ${i}: ${STEP_NAMES[i - 1]}">${label}</button>`;
    if (i < TOTAL) html += `<div class="step-line${done ? ' done' : ''}"></div>`;
  }
  bar.innerHTML = html;
}

function renderFooter() {
  const prev = document.getElementById('btn-prev');
  const next = document.getElementById('btn-next');
  const ctr  = document.getElementById('step-counter');
  prev.style.visibility = currentStep === 1 ? 'hidden' : 'visible';
  next.textContent = currentStep === TOTAL ? 'Save Configuration' : 'Next →';
  ctr.textContent  = `${currentStep} / ${TOTAL}`;
}

function collectCurrent() {
  const fn = collectors[currentStep];
  if (fn) fn();
}

function prev() {
  collectCurrent();
  if (currentStep > 1) { currentStep--; render(); scrollTo(0, 0); }
}

async function next() {
  collectCurrent();
  if (currentStep < TOTAL) { currentStep++; render(); scrollTo(0, 0); }
  else await save();
}

function jumpTo(n) {
  collectCurrent();
  currentStep = n;
  render();
  scrollTo(0, 0);
}

// ============================================================
// Step 1 — Agent identity
// ============================================================

function buildStep1() {
  return `
    <h2 class="step-heading">Your Agent</h2>
    <p class="step-desc">Give your AI companion a name, and tell it who you are.</p>
    <div class="form-group">
      <label for="f-name">Agent Name</label>
      <input type="text" id="f-name" class="form-input" value="${esc(state.agent_name)}" placeholder="Aria" maxlength="60" autofocus>
      <p class="form-hint">Used in system prompts, memory notes, and the console.</p>
    </div>
    <div class="name-preview">
      You are <strong id="name-live">${esc(state.agent_name) || 'your agent'}</strong>.
    </div>
    <div class="form-group" style="margin-top:1.5rem">
      <label for="f-owner-name">Your Name</label>
      <input type="text" id="f-owner-name" class="form-input" value="${esc(state.owner_name)}" placeholder="e.g. Alex" maxlength="60">
      <p class="form-hint">Your name as the agent's owner. Used to personalise memory notes and context.</p>
    </div>`;
}

function bindStep1() {
  const inp  = document.getElementById('f-name');
  const live = document.getElementById('name-live');
  if (inp) inp.addEventListener('input', () => { live.textContent = inp.value || 'your agent'; });
}

function collectStep1() {
  state.agent_name  = val('f-name')        || state.agent_name;
  state.owner_name  = val('f-owner-name');
}

// ============================================================
// Step 2 — Model
// ============================================================

function buildStep2() {
  const ollama = state.model_provider === 'ollama';
  const models = ['claude-sonnet-4-6', 'claude-opus-4-6', 'claude-haiku-4-5-20251001'];
  return `
    <h2 class="step-heading">AI Model</h2>
    <p class="step-desc">Choose the model that powers your agent.</p>
    <div class="provider-tabs">
      <button class="tab ${!ollama ? 'active' : ''}" onclick="setProvider('anthropic')">Anthropic (Claude)</button>
      <button class="tab ${ollama ? 'active' : ''}" onclick="setProvider('ollama')">Ollama (Local)</button>
    </div>
    <div id="anthropic-fields" style="display:${!ollama ? '' : 'none'}">
      <div class="form-group">
        <label for="f-api-key">API Key</label>
        <input type="password" id="f-api-key" class="form-input" value="${esc(state.anthropic_api_key)}" placeholder="sk-ant-...">
        <p class="form-hint">Get your key at <code>console.anthropic.com</code></p>
      </div>
      <div class="form-group">
        <label for="f-model">Model</label>
        <select id="f-model" class="form-input form-select">
          ${models.map(m => `<option value="${m}" ${state.claude_model === m ? 'selected' : ''}>${m}</option>`).join('')}
        </select>
      </div>
    </div>
    <div id="ollama-fields" style="display:${ollama ? '' : 'none'}">
      <div class="callout callout-info">
        Ollama must be running before starting the agent. Tool use support varies by model.
      </div>
      <div class="form-group" style="margin-top:1rem">
        <label for="f-ollama-url">Base URL</label>
        <input type="text" id="f-ollama-url" class="form-input" value="${esc(state.ollama_base_url)}" placeholder="http://localhost:11434/v1">
      </div>
      <div class="form-group">
        <label for="f-ollama-model">Model Name</label>
        <input type="text" id="f-ollama-model" class="form-input" value="${esc(state.ollama_model)}" placeholder="llama3.2">
        <p class="form-hint">Any model pulled with <code>ollama pull &lt;model&gt;</code></p>
      </div>
    </div>
    <div class="form-group" style="margin-top:1.5rem">
      <label for="f-max-tokens">Max Tokens per Reply</label>
      <input type="number" id="f-max-tokens" class="form-input" value="${esc(state.max_tokens)}" min="64" max="8192" step="64">
      <p class="form-hint">Hard ceiling on model output length. Lower = faster + more concise. 512–768 is good for local models; 1024 for Claude.</p>
    </div>`;
}

function collectStep2() {
  state.anthropic_api_key = val('f-api-key') || state.anthropic_api_key;
  state.claude_model      = val('f-model')   || state.claude_model;
  state.ollama_base_url   = val('f-ollama-url')   || state.ollama_base_url;
  state.ollama_model      = val('f-ollama-model')  || state.ollama_model;
  const mt = parseInt(val('f-max-tokens'), 10);
  if (mt > 0) state.max_tokens = mt;
}

function setProvider(p) {
  collectStep2();
  state.model_provider = p;
  renderStep(currentStep);
}

// ============================================================
// Step 3 — Platforms
// ============================================================

function buildStep3() {
  return `
    <h2 class="step-heading">Platforms</h2>
    <p class="step-desc">Choose where your agent lives. Both platforms share the same brain.</p>

    <div class="platform-card ${state.discord_enabled ? 'enabled' : ''}">
      <div class="card-header">
        <div>
          <div class="card-title">Discord</div>
          <div class="card-desc">Respond to @mentions, DMs, or full channel participation</div>
        </div>
        <label class="toggle">
          <input type="checkbox" id="f-discord-on" ${state.discord_enabled ? 'checked' : ''}
            onchange="toggleCard(this, 'discord-body')">
          <span class="slider"></span>
        </label>
      </div>
      <div id="discord-body" class="card-body" style="display:${state.discord_enabled ? '' : 'none'}">
        <div class="form-group">
          <label for="f-discord-token">Bot Token</label>
          <input type="password" id="f-discord-token" class="form-input" value="${esc(state.discord_token)}" placeholder="Paste your bot token">
          <p class="form-hint">Discord Developer Portal → Bot → Token</p>
        </div>
        <div class="form-group">
          <label for="f-guild-ids">Allowed Server IDs <span class="label-opt">(optional)</span></label>
          <input type="text" id="f-guild-ids" class="form-input" value="${esc(state.discord_allowed_guild_ids)}" placeholder="123456789,987654321">
          <p class="form-hint">Comma-separated. Empty = all servers.</p>
        </div>
        <div class="form-group" style="margin-bottom:0">
          <label for="f-channel-ids">Active Channel IDs <span class="label-opt">(optional)</span></label>
          <input type="text" id="f-channel-ids" class="form-input" value="${esc(state.discord_active_channel_ids)}" placeholder="123456789,987654321">
          <p class="form-hint">Channels where the agent responds without @mention.</p>
        </div>
      </div>
    </div>

    <div class="platform-card ${state.sl_enabled ? 'enabled' : ''}">
      <div class="card-header">
        <div>
          <div class="card-title">Second Life / OpenSimulator</div>
          <div class="card-desc">LSL HUD and Cool VL Viewer Lua IM interface</div>
        </div>
        <label class="toggle">
          <input type="checkbox" id="f-sl-on" ${state.sl_enabled ? 'checked' : ''}
            onchange="toggleCard(this, 'sl-body')">
          <span class="slider"></span>
        </label>
      </div>
      <div id="sl-body" class="card-body" style="display:${state.sl_enabled ? '' : 'none'}">
        <div class="form-group">
          <label for="f-sl-secret">Bridge Secret <span class="label-opt">(optional)</span></label>
          <input type="text" id="f-sl-secret" class="form-input" value="${esc(state.sl_bridge_secret)}" placeholder="shared_secret_here">
          <p class="form-hint">Must match <code>SECRET</code> in the LSL HUD and Lua script.</p>
        </div>
        <div class="form-group">
          <label for="f-sl-port">Bridge Port</label>
          <input type="number" id="f-sl-port" class="form-input" value="${esc(state.sl_bridge_port)}" min="1024" max="65535">
        </div>
        <div class="sub-toggle">
          <label class="toggle">
            <input type="checkbox" id="f-opensim-on" ${state.opensim_enabled ? 'checked' : ''}>
            <span class="slider"></span>
          </label>
          <span>OpenSimulator grid (caps replies at 1800 chars by default)</span>
        </div>
      </div>
    </div>

    <div class="callout callout-info">
      The SL bridge always starts on the configured port. Use
      <code>cloudflared tunnel --url http://localhost:${esc(state.sl_bridge_port)}</code>
      to expose it to SL/OpenSim servers.
    </div>`;
}

function collectStep3() {
  state.discord_enabled           = chk('f-discord-on');
  state.discord_token             = val('f-discord-token') || state.discord_token;
  state.discord_allowed_guild_ids = val('f-guild-ids');
  state.discord_active_channel_ids = val('f-channel-ids');
  state.sl_enabled                = chk('f-sl-on');
  state.sl_bridge_secret          = val('f-sl-secret') || state.sl_bridge_secret;
  state.sl_bridge_port            = val('f-sl-port')   || state.sl_bridge_port;
  state.opensim_enabled           = chk('f-opensim-on');
}

function toggleCard(checkbox, bodyId) {
  const body = document.getElementById(bodyId);
  const card = checkbox.closest('.platform-card, .tool-card');
  if (body) body.style.display = checkbox.checked ? '' : 'none';
  if (card) card.classList.toggle('enabled', checkbox.checked);
}

// ============================================================
// Step 4 — Identity
// ============================================================

function buildStep4() {
  return `
    <h2 class="step-heading">Identity</h2>
    <p class="step-desc">Define who your agent is, how they feel, and who they're for. Each file is loaded into the system prompt on every message.</p>
    <div class="form-group">
      <label for="f-agent-md">Agent <span class="label-opt">(agent.md)</span></label>
      <textarea id="f-agent-md" class="form-textarea" rows="10">${esc(state.agent_md)}</textarea>
      <p class="form-hint">Role, purpose, behaviors, boundaries, and roleplay rules.</p>
    </div>
    <div class="form-group" style="margin-top:1.5rem">
      <label for="f-soul-md">Soul <span class="label-opt">(soul.md)</span></label>
      <textarea id="f-soul-md" class="form-textarea" rows="6">${esc(state.soul_md)}</textarea>
      <p class="form-hint">Tone, humor, quirks, and conversational style.</p>
    </div>
    <div class="form-group" style="margin-top:1.5rem">
      <label for="f-user-md">User Profile <span class="label-opt">(user.md)</span></label>
      <textarea id="f-user-md" class="form-textarea" rows="5">${esc(state.user_md)}</textarea>
      <p class="form-hint">Describes the agent's owner — you. Used to personalise every response.</p>
    </div>`;
}

function collectStep4() {
  state.agent_md = val('f-agent-md');
  state.soul_md  = val('f-soul-md');
  state.user_md  = val('f-user-md');
}

function buildStep5() {
  const showSL = state.sl_enabled;
  return `
    <h2 class="step-heading">Tools & Capabilities</h2>
    <p class="step-desc">Choose which tools your agent can use. Tools are used when helpful; the agent does not announce them.</p>

    <div class="tool-card ${state.web_search_enabled ? 'enabled' : ''}">
      <div class="card-header">
        <div>
          <div class="card-title">Web Search</div>
          <div class="card-desc">Search the web for current info, news, shopping, and more</div>
        </div>
        <label class="toggle">
          <input type="checkbox" id="f-search-on" ${state.web_search_enabled ? 'checked' : ''}
            onchange="toggleCard(this, 'search-body')">
          <span class="slider"></span>
        </label>
      </div>
      <div id="search-body" class="card-body" style="display:${state.web_search_enabled ? '' : 'none'}">
        <div class="form-group">
          <label for="f-search-provider">Provider</label>
          <select id="f-search-provider" class="form-input form-select">
            <option value="serper" ${state.search_provider === 'serper' ? 'selected' : ''}>Serper (Google)</option>
            <option value="brave"  ${state.search_provider === 'brave'  ? 'selected' : ''}>Brave Search</option>
          </select>
        </div>
        <div class="form-group" style="margin-bottom:0">
          <label for="f-search-key">API Key</label>
          <input type="password" id="f-search-key" class="form-input" value="${esc(state.search_api_key)}" placeholder="Search provider API key">
          <p class="form-hint">Serper: <code>serper.dev</code> · Brave: <code>api.search.brave.com</code></p>
        </div>
      </div>
    </div>

    <div class="tool-card ${state.notes_enabled ? 'enabled' : ''}">
      <div class="card-header">
        <div>
          <div class="card-title">Notes</div>
          <div class="card-desc">Save and recall persistent notes across conversations</div>
        </div>
        <label class="toggle">
          <input type="checkbox" id="f-notes-on" ${state.notes_enabled ? 'checked' : ''}
            onchange="this.closest('.tool-card').classList.toggle('enabled', this.checked)">
          <span class="slider"></span>
        </label>
      </div>
    </div>

    ${showSL ? `
    <div class="tool-card ${state.sl_action_enabled ? 'enabled' : ''}">
      <div class="card-header">
        <div>
          <div class="card-title">SL Actions</div>
          <div class="card-desc">Send emotes and IM actions in Second Life / OpenSim</div>
        </div>
        <label class="toggle">
          <input type="checkbox" id="f-slaction-on" ${state.sl_action_enabled ? 'checked' : ''}
            onchange="this.closest('.tool-card').classList.toggle('enabled', this.checked)">
          <span class="slider"></span>
        </label>
      </div>
    </div>` : ''}`;
}

function collectStep5() {
  state.web_search_enabled = chk('f-search-on');
  state.search_provider    = val('f-search-provider') || state.search_provider;
  state.search_api_key     = val('f-search-key') || state.search_api_key;
  state.notes_enabled      = chk('f-notes-on');
  const slEl               = document.getElementById('f-slaction-on');
  if (slEl) state.sl_action_enabled = slEl.checked;
}

// ============================================================
// Step 6 — Context & Platform Awareness
// ============================================================

function buildStep6() {
  const paSections = [];
  if (state.discord_enabled)
    paSections.push(`
    <div class="form-group">
      <label for="f-pa-discord">Platform Awareness — Discord</label>
      <textarea id="f-pa-discord" class="form-textarea" rows="8">${esc(state.pa_discord)}</textarea>
    </div>`);
  if (state.sl_enabled)
    paSections.push(`
    <div class="form-group">
      <label for="f-pa-sl">Platform Awareness — Second Life</label>
      <textarea id="f-pa-sl" class="form-textarea" rows="20">${esc(state.pa_sl)}</textarea>
    </div>`);
  if (state.opensim_enabled)
    paSections.push(`
    <div class="form-group">
      <label for="f-pa-opensim">Platform Awareness — OpenSimulator</label>
      <textarea id="f-pa-opensim" class="form-textarea" rows="10">${esc(state.pa_opensim)}</textarea>
    </div>`);

  return `
    <h2 class="step-heading">Context & Platform Awareness</h2>
    <p class="step-desc">Add extra context and edit platform-specific behavior.</p>

    <div class="form-group">
      <label for="f-extra">Additional Context</label>
      <textarea id="f-extra" class="form-textarea" rows="5" placeholder="Extra instructions, specific relationships, environment notes, or anything else that doesn't fit the categories above...">${esc(state.additional_context)}</textarea>
      <p class="form-hint">Free-form. Appended to the system prompt on every message.</p>
    </div>

    ${paSections.length ? `
    <div style="margin-top:1.5rem">
      <div class="section-title" style="margin-bottom:0.75rem">Platform Awareness</div>
      <p class="step-desc" style="margin-top:0;margin-bottom:1rem">Injected per platform — only enabled platforms appear. Describes what the agent can perceive, do, and how to behave.</p>
      ${paSections.join('')}
    </div>` : '<p class="text-dim" style="margin-top:1.5rem">Enable platforms in Step 3 to configure their awareness blocks here.</p>'}`;
}

function collectStep6() {
  state.additional_context = val('f-extra');
  const d = document.getElementById('f-pa-discord');
  const s = document.getElementById('f-pa-sl');
  const o = document.getElementById('f-pa-opensim');
  if (d) state.pa_discord  = d.value;
  if (s) state.pa_sl       = s.value;
  if (o) state.pa_opensim  = o.value;
}

// ============================================================
// Step 7 — Review & Save
// ============================================================

function buildStep7() {
  const modelLabel = state.model_provider === 'ollama'
    ? `Ollama — ${state.ollama_model}`
    : state.claude_model;

  const platforms = [];
  if (state.discord_enabled) platforms.push('<span class="badge">Discord</span>');
  if (state.sl_enabled) platforms.push(`<span class="badge">SL${state.opensim_enabled ? ' / OpenSim' : ''}</span>`);

  const tools = [];
  if (state.web_search_enabled) tools.push('<span class="badge">Web Search</span>');
  if (state.notes_enabled)      tools.push('<span class="badge">Notes</span>');
  if (state.sl_action_enabled && state.sl_enabled) tools.push('<span class="badge">SL Actions</span>');

  return `
    <h2 class="step-heading">Ready to Launch</h2>
    <p class="step-desc">Review your configuration, then save.</p>

    <div class="review-grid">
      <div class="review-card">
        <div class="review-label">Agent</div>
        <div class="review-value">${esc(state.agent_name)}</div>
      </div>
      <div class="review-card">
        <div class="review-label">Model</div>
        <div class="review-value">${esc(modelLabel)}</div>
      </div>
      <div class="review-card">
        <div class="review-label">Platforms</div>
        <div class="review-value">${platforms.length ? platforms.join('') : '<span class="text-dim">None</span>'}</div>
      </div>
      <div class="review-card">
        <div class="review-label">Tools</div>
        <div class="review-value">${tools.length ? tools.join('') : '<span class="text-dim">None</span>'}</div>
      </div>
    </div>

    <div id="save-result"></div>

    <div class="callout callout-info">
      Persona changes take effect immediately. Model, credentials, and platform changes require a restart:
      <code>./run.sh</code>
    </div>`;
}

// ============================================================
// Step registry
// ============================================================

const builders = {
  1: buildStep1, 2: buildStep2, 3: buildStep3,
  4: buildStep4, 5: buildStep5, 6: buildStep6, 7: buildStep7,
};
const binders = { 1: bindStep1 };
const collectors = {
  1: collectStep1, 2: collectStep2, 3: collectStep3,
  4: collectStep4, 5: collectStep5, 6: collectStep6,
};

function renderStep(n) {
  const content = document.getElementById('step-content');
  content.innerHTML = builders[n] ? builders[n]() : `<p>Step ${n}</p>`;
  if (binders[n]) binders[n]();
}

// ============================================================
// Save
// ============================================================

async function save() {
  const payload = {
    env: {
      MODEL_PROVIDER:              state.model_provider,
      ANTHROPIC_API_KEY:           state.anthropic_api_key,
      CLAUDE_MODEL:                state.claude_model,
      OLLAMA_BASE_URL:             state.ollama_base_url,
      OLLAMA_MODEL:                state.ollama_model,
      CLAUDE_MAX_TOKENS:           String(state.max_tokens),
      DISCORD_TOKEN:               state.discord_token,
      DISCORD_ALLOWED_GUILD_IDS:   state.discord_allowed_guild_ids,
      DISCORD_ACTIVE_CHANNEL_IDS:  state.discord_active_channel_ids,
      SL_BRIDGE_SECRET:            state.sl_bridge_secret,
      SL_BRIDGE_PORT:              String(state.sl_bridge_port),
      OPENSIM_ENABLED:             state.opensim_enabled ? 'true' : 'false',
      SEARCH_PROVIDER:             state.search_provider,
      SEARCH_API_KEY:              state.search_api_key,
      OWNER_NAME:                  state.owner_name,
    },
    agent_config: {
      agent_name: state.agent_name,
      identity: {
        agent_md: state.agent_md,
        soul_md:  state.soul_md,
        user_md:  state.user_md,
      },
      additional_context: state.additional_context,
      platform_awareness: {
        discord: state.pa_discord,
        sl:      state.pa_sl,
        opensim: state.pa_opensim,
      },
      tools: {
        web_search: state.web_search_enabled,
        notes:      state.notes_enabled,
        sl_action:  state.sl_action_enabled,
      },
    },
  };

  const btn = document.getElementById('btn-next');
  btn.textContent = 'Saving…';
  btn.disabled = true;

  try {
    const res = await fetch('/setup/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();

    if (data.ok) {
      configured = true;
      document.getElementById('page-title').textContent = 'Settings';
      document.getElementById('save-result').innerHTML = `
        <div class="save-result success">
          <div class="save-icon">✓</div>
          <div>
            <strong>Configuration saved.</strong>
            <p>Persona changes are live. Restart the agent to apply model, credential, and platform changes:</p>
            <code class="code-block">./run.sh</code>
          </div>
        </div>`;
    } else {
      throw new Error(data.error || 'Unknown error');
    }
  } catch (e) {
    document.getElementById('save-result').innerHTML = `
      <div class="save-result error">
        <div class="save-icon">✗</div>
        <div><strong>Save failed.</strong> ${esc(e.message)}</div>
      </div>`;
  }

  btn.textContent = 'Save Configuration';
  btn.disabled = false;
}

// ============================================================
// Boot
// ============================================================

document.addEventListener('DOMContentLoaded', init);
