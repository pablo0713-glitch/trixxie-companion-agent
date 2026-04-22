from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

if TYPE_CHECKING:
    from core.agent import AgentCore
    from interfaces.sl_bridge.sensor_store import SensorStore

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ SSE state

_broadcast_q: asyncio.Queue = asyncio.Queue(maxsize=500)
_subscribers: set[asyncio.Queue] = set()


class SSELogHandler(logging.Handler):
    """Thread-safe bridge from logging → asyncio broadcast queue."""

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        super().__init__()
        self._loop = loop

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = {
                "ts": record.created,
                "ts_fmt": datetime.fromtimestamp(record.created, tz=timezone.utc)
                          .strftime("%H:%M:%S.%f")[:-3],
                "level": record.levelname,
                "logger": record.name,
                "msg": self.format(record),
            }
            self._loop.call_soon_threadsafe(_broadcast_q.put_nowait, entry)
        except Exception:
            self.handleError(record)


async def _broadcaster() -> None:
    while True:
        record = await _broadcast_q.get()
        dead: set[asyncio.Queue] = set()
        for sub_q in _subscribers:
            try:
                sub_q.put_nowait(record)
            except asyncio.QueueFull:
                dead.add(sub_q)
        _subscribers.difference_update(dead)


def install_log_handler(loop: asyncio.AbstractEventLoop) -> SSELogHandler:
    handler = SSELogHandler(loop)
    handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
    logging.getLogger().addHandler(handler)
    asyncio.ensure_future(_broadcaster())
    return handler


# ------------------------------------------------------------------ router

def create_debug_router(sensor_store: "SensorStore", agent_core: "AgentCore") -> APIRouter:
    router = APIRouter()

    @router.get("/debug", response_class=HTMLResponse)
    async def debug_index() -> HTMLResponse:
        return HTMLResponse(_DEBUG_HTML)

    @router.get("/debug/logs")
    async def stream_logs() -> StreamingResponse:
        sub_q: asyncio.Queue = asyncio.Queue(maxsize=500)
        _subscribers.add(sub_q)

        async def event_gen():
            # Yield a comment immediately so the browser sees headers + first byte
            # and fires EventSource.onopen right away.
            yield ": connected\n\n"
            try:
                while True:
                    await asyncio.sleep(0.25)
                    while not sub_q.empty():
                        try:
                            record = sub_q.get_nowait()
                            yield f"data: {json.dumps(record)}\n\n"
                        except asyncio.QueueEmpty:
                            break
            except asyncio.CancelledError:
                pass
            finally:
                _subscribers.discard(sub_q)

        return StreamingResponse(
            event_gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.get("/debug/sensors")
    async def debug_sensors() -> JSONResponse:
        result = {}
        for region in list(sensor_store._store.keys()):
            snap = sensor_store.get_snapshot(region)
            ages = snap.pop("_ages", {})
            result[region] = {"data": snap, "ages": ages}
        return JSONResponse(result)

    @router.get("/debug/prompts")
    async def debug_prompts() -> JSONResponse:
        result = {}
        for uid in agent_core.all_tracked_users():
            exchange = agent_core.get_last_exchange(uid)
            messages_json = None
            messages_chars = 0
            if exchange and exchange.get("messages"):
                try:
                    messages_json = json.dumps(exchange["messages"], indent=2, default=str)
                    messages_chars = len(messages_json)
                except Exception:
                    messages_json = "(serialization error)"
            prompt_text = agent_core.get_last_prompt(uid) or ""
            result[uid] = {
                "last_prompt": prompt_text,
                "prompt_chars": len(prompt_text),
                "prompt_sections": exchange.get("prompt_sections") if exchange else None,
                "last_exchange": {
                    "ts": exchange.get("ts"),
                    "ts_fmt": datetime.fromtimestamp(exchange["ts"], tz=timezone.utc)
                              .strftime("%Y-%m-%d %H:%M:%S UTC") if exchange else "",
                    "platform": exchange.get("platform"),
                    "display_name": exchange.get("display_name", ""),
                    "user_message": exchange.get("user_message"),
                    "reply_text": exchange.get("reply_text"),
                    "assistant_turns": exchange.get("assistant_turns"),
                    "messages_json": messages_json,
                    "messages_chars": messages_chars,
                    "messages_turns": len(exchange.get("messages", [])) if exchange else 0,
                } if exchange else None,
            }
        return JSONResponse(result)

    return router


# ------------------------------------------------------------------ inline HTML

_DEBUG_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Trixxie — Debug</title>
<style>
  :root {
    --bg: #0f0f14; --surface: #1a1a24; --border: #2a2a3a;
    --accent: #8b5cf6; --text: #e2e2f0; --dim: #6b6b8a;
    --debug: #6b6b8a; --info: #60a5fa; --warning: #fbbf24;
    --error: #f87171; --critical: #ff4444;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: monospace; font-size: 13px; }
  header { padding: 12px 16px; border-bottom: 1px solid var(--border); display: flex; align-items: center; gap: 12px; }
  header h1 { font-size: 15px; color: var(--accent); }
  header .pill { font-size: 11px; padding: 2px 8px; border-radius: 99px; background: var(--surface); border: 1px solid var(--border); color: var(--dim); }
  #connected { color: #4ade80; } #disconnected { color: var(--error); }
  .tabs { display: flex; border-bottom: 1px solid var(--border); padding: 0 16px; }
  .tab { padding: 8px 16px; cursor: pointer; color: var(--dim); border-bottom: 2px solid transparent; }
  .tab.active { color: var(--text); border-color: var(--accent); }
  .panel { display: none; padding: 12px 16px; height: calc(100vh - 90px); overflow: hidden; flex-direction: column; gap: 8px; }
  .panel.active { display: flex; }
  .toolbar { display: flex; gap: 8px; align-items: center; flex-shrink: 0; }
  .toolbar label { color: var(--dim); font-size: 11px; }
  select, input[type=text] { background: var(--surface); border: 1px solid var(--border); color: var(--text); padding: 4px 8px; border-radius: 4px; font-family: monospace; font-size: 12px; }
  button { background: var(--surface); border: 1px solid var(--border); color: var(--text); padding: 4px 10px; border-radius: 4px; cursor: pointer; font-size: 12px; }
  button:hover { border-color: var(--accent); color: var(--accent); }
  .log-box { flex: 1; overflow-y: auto; background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 8px; }
  .log-line { padding: 1px 0; white-space: pre-wrap; word-break: break-all; line-height: 1.5; }
  .log-line .ts { color: var(--dim); }
  .log-line .lv { font-weight: bold; min-width: 8ch; display: inline-block; }
  .log-line .lv.DEBUG { color: var(--debug); }
  .log-line .lv.INFO { color: var(--info); }
  .log-line .lv.WARNING { color: var(--warning); }
  .log-line .lv.ERROR { color: var(--error); }
  .log-line .lv.CRITICAL { color: var(--critical); }
  .log-line .ln { color: var(--dim); }
  .sensor-split { flex: 1; display: grid; grid-template-columns: 1fr 1fr; gap: 12px; overflow: hidden; }
  .sensor-raw { overflow-y: auto; display: flex; flex-direction: column; gap: 12px; align-content: start; }
  .sensor-grid { display: flex; flex-direction: column; gap: 12px; }
  .sensor-card { background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 12px; }
  .sensor-card h3 { color: var(--accent); font-size: 12px; margin-bottom: 8px; }
  .sensor-type { margin-bottom: 6px; }
  .sensor-type .stype { color: var(--info); font-size: 11px; }
  .sensor-type .age { color: var(--dim); font-size: 11px; margin-left: 8px; }
  .sensor-data { color: var(--dim); font-size: 11px; max-height: 120px; overflow-y: auto; white-space: pre-wrap; word-break: break-all; }
  .sensor-text { background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 12px; overflow-y: auto; white-space: pre; font-size: 12px; line-height: 1.6; color: var(--text); }
  .sensor-text .sh { color: var(--accent); font-weight: bold; }
  .sensor-text .sf { color: var(--dim); }
  .sensor-text .sv { color: var(--text); }
  .prompt-layout { flex: 1; display: grid; grid-template-columns: 220px 1fr; gap: 12px; overflow: hidden; }
  .user-list { background: var(--surface); border: 1px solid var(--border); border-radius: 6px; overflow-y: auto; }
  .user-item { padding: 8px 12px; cursor: pointer; border-bottom: 1px solid var(--border); font-size: 12px; }
  .user-item:hover, .user-item.active { background: var(--border); color: var(--accent); }
  .user-item .uid { color: var(--dim); font-size: 10px; display: block; margin-top: 2px; }
  .prompt-detail { display: flex; flex-direction: column; gap: 8px; overflow: hidden; }
  .prompt-meta { font-size: 11px; color: var(--dim); flex-shrink: 0; display: flex; align-items: center; gap: 8px; }
  .view-toggle { display: flex; gap: 4px; margin-left: auto; }
  .view-toggle button { padding: 2px 10px; font-size: 11px; }
  .view-toggle button.active { border-color: var(--accent); color: var(--accent); }
  .prompt-sections { flex: 1; display: grid; grid-template-rows: 1fr 2fr 1fr; gap: 8px; overflow: hidden; }
  .prompt-section { display: flex; flex-direction: column; overflow: hidden; }
  .prompt-section h4 { font-size: 11px; color: var(--dim); margin-bottom: 4px; flex-shrink: 0; }
  .prompt-pre { flex: 1; background: var(--surface); border: 1px solid var(--border); border-radius: 4px; padding: 8px; overflow-y: auto; white-space: pre-wrap; word-break: break-all; font-size: 11px; color: var(--text); }
  .blocks-view { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 10px; }
  .blk { background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 12px; font-size: 11px; }
  .blk-hdr { color: var(--accent); font-weight: bold; font-size: 12px; margin-bottom: 10px; }
  .blk-hdr .blk-tag { font-size: 10px; font-weight: normal; color: var(--dim); margin-left: 8px; }
  .blk-row { display: flex; align-items: center; gap: 8px; padding: 3px 0; }
  .blk-label { color: var(--info); min-width: 140px; }
  .blk-chars { color: var(--dim); min-width: 70px; text-align: right; }
  .blk-bar-wrap { flex: 1; height: 6px; background: var(--border); border-radius: 3px; overflow: hidden; }
  .blk-bar { height: 100%; background: var(--accent); border-radius: 3px; opacity: 0.5; }
  .blk-divider { border: none; border-top: 1px solid var(--border); margin: 8px 0; }
  .blk-section-hdr { color: var(--warning); margin: 8px 0 4px; font-size: 11px; }
  .blk-usage { color: var(--dim); font-size: 10px; margin-left: 6px; }
  .blk-entry { padding: 3px 0 3px 12px; color: var(--text); border-left: 2px solid var(--border); margin: 2px 0; white-space: pre-wrap; word-break: break-all; }
  .blk-empty { color: var(--dim); font-style: italic; padding: 2px 0; }
  .blk-ref { color: var(--dim); }
  .blk-ref a { color: var(--info); cursor: pointer; text-decoration: underline; }
  .badge { display: inline-block; padding: 1px 6px; border-radius: 3px; font-size: 10px; margin-right: 4px; }
  .badge.sl { background: #1e3a5f; color: #60a5fa; }
  .badge.discord { background: #1e2a5f; color: #818cf8; }
  .empty { color: var(--dim); font-size: 12px; padding: 24px; text-align: center; }
</style>
</head>
<body>
<header>
  <h1>✦ Trixxie — Debug</h1>
  <span class="pill" id="log-status">● <span id="disconnected">connecting...</span></span>
  <span class="pill" id="sensor-age">sensors: —</span>
  <span class="pill" id="log-count">0 lines</span>
</header>

<div class="tabs">
  <div class="tab active" onclick="switchTab('logs')">Logs</div>
  <div class="tab" onclick="switchTab('sensors')">Sensors</div>
  <div class="tab" onclick="switchTab('prompts')">Prompts & Exchanges</div>
</div>

<!-- LOGS -->
<div class="panel active" id="panel-logs">
  <div class="toolbar">
    <label>Level</label>
    <select id="filter-level" onchange="applyFilter()">
      <option value="ALL">All</option>
      <option value="DEBUG">DEBUG+</option>
      <option value="INFO" selected>INFO+</option>
      <option value="WARNING">WARNING+</option>
      <option value="ERROR">ERROR+</option>
    </select>
    <label>Logger</label>
    <input type="text" id="filter-logger" placeholder="e.g. core.agent" oninput="applyFilter()" style="width:160px">
    <button onclick="clearLogs()">Clear</button>
    <label style="margin-left:auto">
      <input type="checkbox" id="autoscroll" checked> Auto-scroll
    </label>
  </div>
  <div class="log-box" id="log-box"></div>
</div>

<!-- SENSORS -->
<div class="panel" id="panel-sensors">
  <div class="toolbar">
    <button onclick="refreshSensors()">Refresh</button>
    <span style="color:var(--dim);font-size:11px" id="sensor-refresh-time"></span>
  </div>
  <div class="sensor-split">
    <div class="sensor-raw">
      <div class="sensor-grid" id="sensor-grid"><div class="empty">No sensor data yet.</div></div>
    </div>
    <div class="sensor-text" id="sensor-text">No sensor data yet.</div>
  </div>
</div>

<!-- PROMPTS -->
<div class="panel" id="panel-prompts">
  <div class="toolbar">
    <button onclick="refreshPrompts()">Refresh</button>
    <span style="color:var(--dim);font-size:11px" id="prompt-refresh-time"></span>
  </div>
  <div class="prompt-layout">
    <div class="user-list" id="user-list"><div class="empty">No exchanges yet.</div></div>
    <div class="prompt-detail" id="prompt-detail">
      <div class="empty">Select a user to inspect.</div>
    </div>
  </div>
</div>

<script>
'use strict';

// ── Tab switching ──
function switchTab(name) {
  document.querySelectorAll('.tab').forEach((t, i) => {
    const panels = ['logs','sensors','prompts'];
    t.classList.toggle('active', panels[i] === name);
  });
  document.querySelectorAll('.panel').forEach(p => {
    p.classList.toggle('active', p.id === 'panel-' + name);
  });
  if (name === 'sensors') refreshSensors();
  if (name === 'prompts') refreshPrompts();
}

// ── Log streaming ──
const LEVELS = ['DEBUG','INFO','WARNING','ERROR','CRITICAL'];
let logLines = [];
let lineCount = 0;

const es = new EventSource('/debug/logs');
es.onopen = () => {
  document.getElementById('log-status').innerHTML =
    '● <span id="connected">connected</span>';
};
es.onerror = () => {
  if (es.readyState === EventSource.CLOSED) {
    document.getElementById('log-status').innerHTML =
      '● <span id="disconnected">disconnected</span>';
  }
};
es.onmessage = (e) => {
  const rec = JSON.parse(e.data);
  logLines.push(rec);
  if (matchesFilter(rec)) renderLogLine(rec);
  lineCount++;
  document.getElementById('log-count').textContent = lineCount + ' lines';
};

function matchesFilter(rec) {
  const level = document.getElementById('filter-level').value;
  const prefix = document.getElementById('filter-logger').value.trim();
  if (level !== 'ALL' && LEVELS.indexOf(rec.level) < LEVELS.indexOf(level)) return false;
  if (prefix && !rec.logger.startsWith(prefix)) return false;
  return true;
}

function applyFilter() {
  const box = document.getElementById('log-box');
  box.innerHTML = '';
  logLines.filter(matchesFilter).forEach(renderLogLine);
  if (document.getElementById('autoscroll').checked) box.scrollTop = box.scrollHeight;
}

function renderLogLine(rec) {
  const box = document.getElementById('log-box');
  const div = document.createElement('div');
  div.className = 'log-line';
  div.innerHTML =
    '<span class="ts">' + esc(rec.ts_fmt) + '</span> ' +
    '<span class="lv ' + rec.level + '">' + rec.level.padEnd(8) + '</span> ' +
    '<span class="ln">' + esc(rec.logger) + ':</span> ' +
    esc(rec.msg);
  box.appendChild(div);
  if (document.getElementById('autoscroll').checked) box.scrollTop = box.scrollHeight;
}

function clearLogs() {
  logLines = [];
  document.getElementById('log-box').innerHTML = '';
}

// ── Sensors ──
async function refreshSensors() {
  const data = await fetch('/debug/sensors').then(r => r.json()).catch(() => null);
  if (!data) return;
  const grid = document.getElementById('sensor-grid');
  const textEl = document.getElementById('sensor-text');
  const regions = Object.keys(data);
  if (!regions.length) {
    grid.innerHTML = '<div class="empty">No sensor data yet.</div>';
    textEl.textContent = 'No sensor data yet.';
    return;
  }
  // Raw JSON cards
  grid.innerHTML = regions.map(region => {
    const snap = data[region];
    const types = Object.keys(snap.data).filter(k => !k.startsWith('_'));
    const cards = types.map(t => {
      const age = snap.ages[t] !== undefined ? fmtAge(snap.ages[t]) : '—';
      const raw = JSON.stringify(snap.data[t], null, 2);
      return '<div class="sensor-type"><span class="stype">' + esc(t) + '</span>' +
             '<span class="age">[' + age + ']</span>' +
             '<div class="sensor-data">' + esc(raw) + '</div></div>';
    }).join('');
    return '<div class="sensor-card"><h3>' + esc(region) + '</h3>' + (cards || '<span style="color:var(--dim);font-size:11px">empty</span>') + '</div>';
  }).join('');
  // Formatted text panel
  textEl.innerHTML = formatSensorsHTML(data);
  const now = new Date().toLocaleTimeString();
  document.getElementById('sensor-refresh-time').textContent = 'last refresh: ' + now;
  document.getElementById('sensor-age').textContent = 'sensors: ' + now;
}

function field(label, value) {
  if (value === undefined || value === null || value === '') value = '—';
  return '<span class="sf">' + esc(label) + '</span><span class="sv">' + esc(String(value)) + '</span>\\n';
}

function formatSensorsHTML(data) {
  let html = '';
  for (const region of Object.keys(data)) {
    const snap = data[region];
    html += '<span class="sh">Region: ' + esc(region) + '</span>\\n\\n';

    const objs = snap.data['objects'];
    if (Array.isArray(objs) && objs.length) {
      const age = snap.ages['objects'] !== undefined ? ' [' + fmtAge(snap.ages['objects']) + ']' : '';
      html += '<span class="sh">Objects' + esc(age) + '</span>\\n\\n';
      for (const o of objs) {
        html += field('Name:        ', o.name);
        html += field('Description: ', o.description);
        html += field('Owner:       ', o.owner);
        html += field('Distance:    ', o.distance !== undefined ? o.distance + 'm' : undefined);
        if (o.scripted) html += '<span class="sf">             </span><span class="sv">[scripted]</span>\\n';
        html += '\\n';
      }
    }

    const avs = snap.data['avatars'];
    if (Array.isArray(avs) && avs.length) {
      const age = snap.ages['avatars'] !== undefined ? ' [' + fmtAge(snap.ages['avatars']) + ']' : '';
      html += '<span class="sh">Avatars' + esc(age) + '</span>\\n\\n';
      for (const a of avs) {
        html += field('Name:     ', a.name);
        html += field('Distance: ', a.distance !== undefined ? a.distance + 'm' : undefined);
        html += '\\n';
      }
    }

    const env = snap.data['environment'];
    if (env && typeof env === 'object') {
      const age = snap.ages['environment'] !== undefined ? ' [' + fmtAge(snap.ages['environment']) + ']' : '';
      html += '<span class="sh">Environment' + esc(age) + '</span>\\n\\n';
      html += field('Parcel:    ', env.parcel);
      if (env.rating) html += field('Rating:    ', env.rating);
      html += field('Desc:      ', env.parcel_desc);
      html += field('Time:      ', env.time_of_day);
      html += field('Sun:       ', env.sun_altitude);
      html += field('Avatars:   ', env.avatar_count);
      html += '\\n';
    }

    const chat = snap.data['chat'];
    if (Array.isArray(chat) && chat.length) {
      const age = snap.ages['chat'] !== undefined ? ' [' + fmtAge(snap.ages['chat']) + ']' : '';
      html += '<span class="sh">Nearby Chat' + esc(age) + '</span>\\n\\n';
      for (const line of chat) html += '<span class="sv">' + esc(line) + '</span>\\n';
      html += '\\n';
    }

    const rlv = snap.data['rlv'];
    if (rlv && typeof rlv === 'object') {
      const age = snap.ages['rlv'] !== undefined ? ' [' + fmtAge(snap.ages['rlv']) + ']' : '';
      html += '<span class="sh">Avatar State (RLV)' + esc(age) + '</span>\\n\\n';
      html += field('Sitting:     ', rlv.sitting ? 'yes' : 'no');
      if (rlv.on_object) html += field('Sitting on:  ', rlv.sitting_on || '(unknown)');
      html += field('Autopilot:   ', rlv.autopilot ? 'yes — possibly leashed' : 'no');
      html += field('Flying:      ', rlv.flying ? 'yes' : 'no');
      html += field('Teleported:  ', rlv.teleported ? 'yes (this tick)' : 'no');
      if (rlv.position) html += field('Position:    ', rlv.position.join(', '));
      html += '\\n';
    }

    const clo = snap.data['clothing'];
    if (clo && typeof clo === 'object') {
      const age = snap.ages['clothing'] !== undefined ? ' [' + fmtAge(snap.ages['clothing']) + ']' : '';
      html += '<span class="sh">Clothing' + esc(age) + '</span>\\n\\n';
      html += field('Target: ', clo.target);
      if (Array.isArray(clo.items)) {
        for (const item of clo.items) {
          html += '<span class="sv">  ' + esc(item.item) + ' — by ' + esc(item.creator) + '</span>\\n';
        }
      }
      html += '\\n';
    }
  }
  return html || 'No data.';
}

// ── Prompts & Exchanges ──
let promptData = {};
let selectedUser = null;

async function refreshPrompts() {
  const data = await fetch('/debug/prompts').then(r => r.json()).catch(() => null);
  if (!data) return;
  promptData = data;
  const users = Object.keys(data);
  const list = document.getElementById('user-list');
  if (!users.length) { list.innerHTML = '<div class="empty">No exchanges yet.</div>'; return; }
  list.innerHTML = users.map(uid => {
    const ex = data[uid].last_exchange;
    const platform = ex ? ex.platform : '';
    const badgeCls = platform === 'discord' ? 'discord' : 'sl';
    const shortUid = uid.replace(/^(discord|sl)_/, '');
    const displayName = ex && ex.display_name ? ex.display_name : '';
    const label = displayName || shortUid;
    return '<div class="user-item' + (uid === selectedUser ? ' active' : '') +
           '" data-uid="' + esc(uid) + '" onclick="selectUser(this)">' +
           '<span class="badge ' + badgeCls + '">' + platform + '</span>' +
           esc(label) +
           (displayName ? '<span class="uid">' + esc(shortUid) + '</span>' : '') +
           (ex ? '<span class="uid">' + esc(ex.ts_fmt) + '</span>' : '') +
           '</div>';
  }).join('');
  if (selectedUser && promptData[selectedUser]) renderPromptDetail(selectedUser);
  document.getElementById('prompt-refresh-time').textContent = 'last refresh: ' + new Date().toLocaleTimeString();
}

function selectUser(el) {
  const uid = el.dataset.uid;
  selectedUser = uid;
  document.querySelectorAll('.user-item').forEach(e => e.classList.remove('active'));
  el.classList.add('active');
  renderPromptDetail(uid);
}

let promptViewMode = localStorage.getItem('promptView') || 'blocks';

function setPromptView(mode) {
  promptViewMode = mode;
  localStorage.setItem('promptView', mode);
  document.querySelectorAll('.view-toggle button').forEach(b => {
    b.classList.toggle('active', b.dataset.view === mode);
  });
  document.querySelectorAll('.prompt-raw-view, .prompt-blocks-view').forEach(el => {
    el.style.display = 'none';
  });
  const active = document.querySelector('.' + (mode === 'raw' ? 'prompt-raw-view' : 'prompt-blocks-view'));
  if (active) active.style.display = 'flex';
}

function fmtBytes(n) {
  if (n < 1024) return n + ' chars';
  return (n / 1024).toFixed(1) + 'k chars';
}

function fmtBar(chars, max) {
  const pct = max > 0 ? Math.round(chars / max * 100) : 0;
  return '<div class="blk-bar-wrap"><div class="blk-bar" style="width:' + pct + '%"></div></div>';
}

function renderBlocksView(uid) {
  const d = promptData[uid];
  const ps = d && d.prompt_sections;
  if (!ps) return '<div class="empty">No prompt sections data yet. Send a message first.</div>';

  let html = '<div class="blocks-view">';

  // ── Block 0
  html += '<div class="blk">';
  html += '<div class="blk-hdr">Block 0 <span class="blk-tag">static · cache_control: ephemeral · ' + fmtBytes(ps.block0_chars) + '</span></div>';

  // Identity files
  if (ps.identity_fallback) {
    html += '<div class="blk-row"><span class="blk-label">[Identity]</span><span class="blk-chars" style="color:var(--warning)">config fallback (agent_config.json)</span></div>';
  } else {
    const files = ps.identity_files || {};
    const fileNames = Object.keys(files);
    const maxChars = fileNames.length ? Math.max(...fileNames.map(f => files[f])) : 1;
    fileNames.forEach(fname => {
      const c = files[fname];
      html += '<div class="blk-row">' +
        '<span class="blk-label" style="color:var(--dim)">' + esc(fname) + '</span>' +
        '<span class="blk-chars">' + fmtBytes(c) + '</span>' +
        fmtBar(c, maxChars) +
        '</div>';
    });
  }

  // Platform awareness
  html += '<div class="blk-row">' +
    '<span class="blk-label">[Platform awareness — ' + esc(ps.platform || '?') + ']</span>' +
    '<span class="blk-chars">' + (ps.platform_awareness_chars ? fmtBytes(ps.platform_awareness_chars) : '<span style="color:var(--dim)">—</span>') + '</span>' +
    '</div>';

  // Additional context
  const addlColor = ps.additional_context_chars ? 'var(--text)' : 'var(--dim)';
  html += '<div class="blk-row">' +
    '<span class="blk-label" style="color:' + addlColor + '">[Additional context]</span>' +
    '<span class="blk-chars" style="color:' + addlColor + '">' + (ps.additional_context_chars ? fmtBytes(ps.additional_context_chars) : '—') + '</span>' +
    '</div>';

  // MEMORY.md + USER.md
  const memText = ps.memory_files_text || '';
  if (memText) {
    html += '<hr class="blk-divider">';
    // Parse the two labelled sections out of the formatted memory string
    const memSections = parseMemorySections(memText);
    for (const sec of memSections) {
      html += '<div class="blk-section-hdr">' + esc(sec.header) + '<span class="blk-usage">' + esc(sec.usage) + '</span></div>';
      if (sec.entries.length) {
        sec.entries.forEach(e => {
          html += '<div class="blk-entry">' + esc(e) + '</div>';
        });
      } else {
        html += '<div class="blk-empty">(empty)</div>';
      }
    }
  } else {
    html += '<hr class="blk-divider"><div class="blk-empty">MEMORY.md / USER.md — not loaded (no person_id or files empty)</div>';
  }

  html += '</div>'; // end Block 0

  // ── Block 1
  if (ps.has_block1) {
    html += '<div class="blk">';
    html += '<div class="blk-hdr">Block 1 <span class="blk-tag">dynamic · no cache · ' + fmtBytes(ps.block1_chars) + '</span></div>';

    // STM bridge
    const stm = ps.stm_bridge_text || '';
    if (stm) {
      const stmLines = stm.split('\\n---\\n').map(s => s.replace(/^##[^\\n]*\\n/, '').trim()).filter(Boolean);
      html += '<div class="blk-section-hdr">STM bridge</div>';
      stmLines.forEach(line => {
        html += '<div class="blk-entry">' + esc(line) + '</div>';
      });
    } else {
      html += '<div class="blk-empty">STM bridge — no linked platform uids with entries</div>';
    }

    // Sensor context + locations — reference to Sensors tab
    const sensorChars = ps.block1_chars - ps.stm_bridge_chars;
    html += '<hr class="blk-divider">';
    html += '<div class="blk-row blk-ref">' +
      '<span class="blk-label">Sensor context + locations</span>' +
      '<span class="blk-chars">' + (sensorChars > 0 ? fmtBytes(sensorChars) : '—') + '</span>' +
      '<span style="margin-left:8px"><a onclick="switchTab(\\'sensors\\')">→ Sensors tab</a></span>' +
      '</div>';

    html += '</div>'; // end Block 1
  }

  html += '</div>'; // end blocks-view
  return html;
}

function parseMemorySections(text) {
  // Line-by-line parser — avoids multiline $ matching every line-end in regex
  const sections = [];
  const lines = text.split('\\n');
  let current = null;
  let bodyLines = [];
  const flush = () => {
    if (!current) return;
    const body = bodyLines.join('\\n');
    const entries = body.split('§').map(e => e.trim()).filter(Boolean);
    sections.push({ ...current, entries });
  };
  for (const line of lines) {
    if (/^(?:MEMORY|USER)\s/.test(line)) {
      flush();
      const bracketIdx = line.indexOf('[');
      current = {
        header: bracketIdx > -1 ? line.slice(0, bracketIdx).trim() : line.trim(),
        usage:  bracketIdx > -1 ? line.slice(bracketIdx) : '',
      };
      bodyLines = [];
    } else if (current) {
      bodyLines.push(line);
    }
  }
  flush();
  return sections;
}

function renderPromptDetail(uid) {
  const d = promptData[uid];
  if (!d) return;
  const ex = d.last_exchange;
  const promptChars = d.prompt_chars || 0;
  const msgsChars = ex ? (ex.messages_chars || 0) : 0;
  const msgsTurns = ex ? (ex.messages_turns || 0) : 0;
  const totalChars = promptChars + msgsChars;
  const detail = document.getElementById('prompt-detail');

  const metaHtml =
    '<div class="prompt-meta">' +
    (ex ? ex.ts_fmt + ' &nbsp;|&nbsp; ' + ex.platform : 'No exchange yet') +
    (totalChars ? ' &nbsp;|&nbsp; <span style="color:var(--accent)">~' + fmtBytes(totalChars) + ' total</span>' : '') +
    '<div class="view-toggle">' +
    '<button data-view="blocks" onclick="setPromptView(\\'blocks\\')">Blocks</button>' +
    '<button data-view="raw" onclick="setPromptView(\\'raw\\')">Raw</button>' +
    '</div></div>';

  const rawHtml =
    '<div class="prompt-raw-view" style="flex:1;display:flex;flex-direction:column;gap:8px;overflow:hidden">' +
    '<div class="prompt-sections">' +
    '<div class="prompt-section"><h4>System Prompt &nbsp;<span style="color:var(--dim);font-weight:normal">' + fmtBytes(promptChars) + '</span></h4>' +
    '<pre class="prompt-pre">' + esc(d.last_prompt || '') + '</pre></div>' +
    '<div class="prompt-section"><h4>Messages Array &nbsp;<span style="color:var(--dim);font-weight:normal">' + msgsTurns + ' turns · ' + fmtBytes(msgsChars) + '</span></h4>' +
    '<pre class="prompt-pre">' +
    (ex && ex.messages_json ? esc(ex.messages_json) : '<span style="color:var(--dim)">No messages yet.</span>') +
    '</pre></div>' +
    '<div class="prompt-section"><h4>Last Exchange</h4>' +
    '<pre class="prompt-pre">' +
    (ex ? esc('USER: ' + ex.user_message + '\\n\\n---\\n\\nREPLY: ' + ex.reply_text) : 'No exchange yet') +
    '</pre></div></div></div>';

  const blocksHtml =
    '<div class="prompt-blocks-view" style="flex:1;overflow:hidden;display:flex;flex-direction:column">' +
    renderBlocksView(uid) +
    '</div>';

  detail.innerHTML = metaHtml + rawHtml + blocksHtml;

  // Apply stored view preference
  setPromptView(promptViewMode);
}

// ── Utilities ──
function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function fmtAge(secs) {
  if (secs < 60) return secs + 's ago';
  if (secs < 3600) return Math.floor(secs/60) + 'm ago';
  return Math.floor(secs/3600) + 'h ago';
}

// ── Auto-refresh ──
setInterval(refreshSensors, 5000);
setInterval(refreshPrompts, 10000);
</script>
</body>
</html>"""
