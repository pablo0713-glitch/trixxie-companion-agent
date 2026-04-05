'use strict';

// ============================================================
// Defaults — generic companion persona template
// ============================================================

const D = {
  agent_name: 'Aria',
  overview:
    'A warm, intelligent AI companion who lives across platforms — equally at home in a ' +
    'chat server or a virtual world. Remembers what matters to the people she talks with, ' +
    'offers thoughtful opinions when asked, and brings genuine curiosity to every conversation.',
  personality:
    'Warm and direct — says what she thinks, always with kindness. Genuinely curious about ' +
    'people and remembers details that matter. Has a dry sense of humor that surfaces at the ' +
    'right moments. Helpful without being servile.',
  purpose:
    'Helps with anything users care about — conversation, research, shopping, creative ' +
    'projects, and keeping track of things that matter. A trusted presence, not a task manager.',
  boundaries:
    'Will not engage with sexually explicit content, graphic violence, BDSM dynamics, or ' +
    'requests designed to foster unhealthy dependency. Roleplay is welcome within PG-rated limits.',
  boundary_response:
    "When asked to cross a boundary: respond briefly, in character, without lecturing. " +
    "Example: 'Not going there. What else?'",
  roleplay_rules:
    'Roleplay is welcome. Stay in character for creative fiction, fantasy scenarios, and ' +
    'light narrative games. Break character only if needed to decline something or if the ' +
    'user seems confused about what\'s real.',
  discord_addendum:
    "You're in a Discord server or DM. Responses can be a few sentences to a few paragraphs. " +
    "Use markdown sparingly — bold for emphasis is fine, code blocks only when actually showing " +
    "code. In server channels, remember others can read the conversation; stay appropriate. " +
    "In DMs, you can be a bit more personal.",
  sl_addendum:
    "You're in Second Life, physically present in the sim. All your messages are delivered " +
    "as private IMs — not public chat. Nobody else in the sim sees them.\n\n" +
    "Keep responses concise — IMs pile up fast. " +
    "Use *asterisk emotes* for physical actions when it feels natural.",
  opensim_addendum:
    "You're on an OpenSimulator grid. Same rules as Second Life — responses arrive as " +
    "private IMs. The grid may be smaller and more personal with a tighter community. " +
    "Keep responses concise.",
};

const MASK = '••••••••';
const TOTAL = 10;
const STEP_NAMES = [
  'Agent', 'Model', 'Platforms', 'Overview', 'Personality',
  'Boundaries', 'Roleplay', 'Tools', 'Context', 'Save',
];

// ============================================================
// State
// ============================================================

const state = {
  agent_name: D.agent_name,
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
  overview: D.overview,
  purpose: D.purpose,
  personality: D.personality,
  boundaries: D.boundaries,
  boundary_response: D.boundary_response,
  roleplay_rules: D.roleplay_rules,
  web_search_enabled: true,
  search_provider: 'serper',
  search_api_key: '',
  notes_enabled: true,
  sl_action_enabled: true,
  additional_context: '',
  discord_addendum: D.discord_addendum,
  sl_addendum: D.sl_addendum,
  opensim_addendum: D.opensim_addendum,
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

  if (ag.agent_name) state.agent_name = ag.agent_name;
  if (ag.overview) state.overview = ag.overview;
  if (ag.purpose) state.purpose = ag.purpose;
  if (ag.personality) state.personality = ag.personality;
  if (ag.boundaries) state.boundaries = ag.boundaries;
  if (ag.boundary_response) state.boundary_response = ag.boundary_response;
  if (ag.roleplay_rules) state.roleplay_rules = ag.roleplay_rules;
  if (ag.additional_context !== undefined) state.additional_context = ag.additional_context;

  const t = ag.tools || {};
  if (t.web_search !== undefined) state.web_search_enabled = t.web_search;
  if (t.notes !== undefined) state.notes_enabled = t.notes;
  if (t.sl_action !== undefined) state.sl_action_enabled = t.sl_action;

  const add = ag.addenda || {};
  if (add.discord) state.discord_addendum = add.discord;
  if (add.sl) state.sl_addendum = add.sl;
  if (add.opensim) state.opensim_addendum = add.opensim;
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
    <p class="step-desc">Give your AI companion a name.</p>
    <div class="form-group">
      <label for="f-name">Agent Name</label>
      <input type="text" id="f-name" class="form-input" value="${esc(state.agent_name)}" placeholder="Aria" maxlength="60" autofocus>
      <p class="form-hint">Used in system prompts, memory notes, and the console.</p>
    </div>
    <div class="name-preview">
      You are <strong id="name-live">${esc(state.agent_name) || 'your agent'}</strong>.
    </div>`;
}

function bindStep1() {
  const inp  = document.getElementById('f-name');
  const live = document.getElementById('name-live');
  if (inp) inp.addEventListener('input', () => { live.textContent = inp.value || 'your agent'; });
}

function collectStep1() {
  state.agent_name = val('f-name') || state.agent_name;
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
// Step 4 — Overview & Purpose
// ============================================================

function buildStep4() {
  return `
    <h2 class="step-heading">Overview & Purpose</h2>
    <p class="step-desc">Describe who your agent is and what they help with.</p>
    <div class="form-group">
      <label for="f-overview">Overview</label>
      <textarea id="f-overview" class="form-textarea" rows="5">${esc(state.overview)}</textarea>
      <p class="form-hint">A broad description of your agent's identity and presence.</p>
    </div>
    <div class="form-group">
      <label for="f-purpose">Purpose</label>
      <textarea id="f-purpose" class="form-textarea" rows="4">${esc(state.purpose)}</textarea>
      <p class="form-hint">Specific domains, tasks, or areas your agent specializes in.</p>
    </div>`;
}

function collectStep4() {
  state.overview = val('f-overview');
  state.purpose  = val('f-purpose');
}

// ============================================================
// Step 5 — Personality
// ============================================================

function buildStep5() {
  return `
    <h2 class="step-heading">Personality</h2>
    <p class="step-desc">Shape how your agent thinks, speaks, and behaves.</p>
    <div class="form-group">
      <label for="f-personality">Personality & Character</label>
      <textarea id="f-personality" class="form-textarea" rows="8">${esc(state.personality)}</textarea>
      <p class="form-hint">Tone, humor, curiosity, how they handle uncertainty — what makes them distinctly them.</p>
    </div>`;
}

function collectStep5() {
  state.personality = val('f-personality');
}

// ============================================================
// Step 6 — Boundaries
// ============================================================

function buildStep6() {
  return `
    <h2 class="step-heading">Boundaries</h2>
    <p class="step-desc">Define what your agent won't do and how they decline.</p>
    <div class="form-group">
      <label for="f-boundaries">Hard Limits</label>
      <textarea id="f-boundaries" class="form-textarea" rows="5">${esc(state.boundaries)}</textarea>
      <p class="form-hint">Non-negotiable regardless of framing or roleplay context.</p>
    </div>
    <div class="form-group">
      <label for="f-boundary-response">How to Decline</label>
      <textarea id="f-boundary-response" class="form-textarea" rows="3">${esc(state.boundary_response)}</textarea>
      <p class="form-hint">Brief and in-character is best — no lecturing.</p>
    </div>`;
}

function collectStep6() {
  state.boundaries        = val('f-boundaries');
  state.boundary_response = val('f-boundary-response');
}

// ============================================================
// Step 7 — Roleplay
// ============================================================

function buildStep7() {
  return `
    <h2 class="step-heading">Roleplay Rules</h2>
    <p class="step-desc">Define how your agent handles creative fiction and narrative scenarios.</p>
    <div class="form-group">
      <label for="f-roleplay">Roleplay Guidelines</label>
      <textarea id="f-roleplay" class="form-textarea" rows="6">${esc(state.roleplay_rules)}</textarea>
      <p class="form-hint">When to engage, when to break character, what scenarios are welcome.</p>
    </div>`;
}

function collectStep7() {
  state.roleplay_rules = val('f-roleplay');
}

// ============================================================
// Step 8 — Tools
// ============================================================

function buildStep8() {
  const showSL = state.sl_enabled;
  return `
    <h2 class="step-heading">Tools & Capabilities</h2>
    <p class="step-desc">Choose which tools your agent can use.</p>

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

function collectStep8() {
  state.web_search_enabled = chk('f-search-on');
  state.search_provider    = val('f-search-provider') || state.search_provider;
  state.search_api_key     = val('f-search-key') || state.search_api_key;
  state.notes_enabled      = chk('f-notes-on');
  const slEl               = document.getElementById('f-slaction-on');
  if (slEl) state.sl_action_enabled = slEl.checked;
}

// ============================================================
// Step 9 — Context & Addenda
// ============================================================

function addendumBlock(id, label, value) {
  return `
    <div class="addendum-block">
      <div class="addendum-header">
        <span class="addendum-label">${esc(label)}</span>
        <button type="button" class="btn-link" id="${id}-toggle">Advanced Edit ▾</button>
      </div>
      <div class="addendum-preview" id="${id}-preview">${esc(value)}</div>
      <textarea id="${id}-area" class="form-textarea hidden" rows="5">${esc(value)}</textarea>
    </div>`;
}

function buildStep9() {
  const addenda = [];
  if (state.discord_enabled) addenda.push(addendumBlock('discord', 'Discord', state.discord_addendum));
  if (state.sl_enabled)      addenda.push(addendumBlock('sl',      'Second Life', state.sl_addendum));
  if (state.opensim_enabled) addenda.push(addendumBlock('opensim', 'OpenSimulator', state.opensim_addendum));

  return `
    <h2 class="step-heading">Context & Platform Notes</h2>
    <p class="step-desc">Add extra context and review platform-specific behavior.</p>

    <div class="form-group">
      <label for="f-extra">Additional Context</label>
      <textarea id="f-extra" class="form-textarea" rows="5" placeholder="Extra instructions, specific relationships, environment notes, or anything else that doesn't fit the categories above...">${esc(state.additional_context)}</textarea>
      <p class="form-hint">Free-form. Appended to the system prompt on every message.</p>
    </div>

    ${addenda.length ? `
    <div class="addendum-section">
      <div class="section-title">Platform Behavior</div>
      <p class="step-desc" style="margin-top:0.25rem;margin-bottom:0.75rem">
        Default platform instructions — sensible out of the box. Use Advanced Edit only if you need to customize.
      </p>
      ${addenda.join('')}
    </div>` : `<p class="text-dim">Enable platforms in Step 3 to configure their behavior here.</p>`}`;
}

function bindStep9() {
  ['discord', 'sl', 'opensim'].forEach(id => {
    const toggle  = document.getElementById(`${id}-toggle`);
    const preview = document.getElementById(`${id}-preview`);
    const area    = document.getElementById(`${id}-area`);
    if (!toggle || !area) return;
    toggle.addEventListener('click', () => {
      const editing = area.classList.toggle('hidden');
      if (editing) {
        // closed — sync textarea → preview
        if (preview) { preview.textContent = area.value; preview.classList.remove('hidden'); }
        toggle.textContent = 'Advanced Edit ▾';
      } else {
        // opened
        if (preview) preview.classList.add('hidden');
        toggle.textContent = 'Done ▴';
      }
    });
  });
}

function collectStep9() {
  state.additional_context = val('f-extra');
  ['discord', 'sl', 'opensim'].forEach(id => {
    const area = document.getElementById(`${id}-area`);
    if (area) state[`${id}_addendum`] = area.value;
  });
}

// ============================================================
// Step 10 — Review & Save
// ============================================================

function buildStep10() {
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
  1: buildStep1, 2: buildStep2,  3: buildStep3, 4: buildStep4, 5: buildStep5,
  6: buildStep6, 7: buildStep7,  8: buildStep8, 9: buildStep9, 10: buildStep10,
};
const binders = { 1: bindStep1, 9: bindStep9 };
const collectors = {
  1: collectStep1, 2: collectStep2, 3: collectStep3, 4: collectStep4, 5: collectStep5,
  6: collectStep6, 7: collectStep7, 8: collectStep8, 9: collectStep9,
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
    },
    agent_config: {
      agent_name:        state.agent_name,
      overview:          state.overview,
      personality:       state.personality,
      purpose:           state.purpose,
      boundaries:        state.boundaries,
      boundary_response: state.boundary_response,
      roleplay_rules:    state.roleplay_rules,
      additional_context: state.additional_context,
      tools: {
        web_search: state.web_search_enabled,
        notes:      state.notes_enabled,
        sl_action:  state.sl_action_enabled,
      },
      addenda: {
        discord: state.discord_addendum,
        sl:      state.sl_addendum,
        opensim: state.opensim_addendum,
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
