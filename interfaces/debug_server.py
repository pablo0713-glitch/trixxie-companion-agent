from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from fastapi import APIRouter, Request
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
    async def stream_logs(request: Request) -> StreamingResponse:
        sub_q: asyncio.Queue = asyncio.Queue(maxsize=200)
        _subscribers.add(sub_q)

        async def event_gen():
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        record = await asyncio.wait_for(sub_q.get(), timeout=15.0)
                        yield f"data: {json.dumps(record)}\n\n"
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
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
            result[uid] = {
                "last_prompt": agent_core.get_last_prompt(uid),
                "last_exchange": {
                    "ts": exchange.get("ts"),
                    "ts_fmt": datetime.fromtimestamp(exchange["ts"], tz=timezone.utc)
                              .strftime("%Y-%m-%d %H:%M:%S UTC") if exchange else "",
                    "platform": exchange.get("platform"),
                    "user_message": exchange.get("user_message"),
                    "reply_text": exchange.get("reply_text"),
                    "assistant_turns": exchange.get("assistant_turns"),
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
<title>Agent Debug</title>
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
  .sensor-grid { flex: 1; overflow-y: auto; display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 12px; align-content: start; }
  .sensor-card { background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 12px; }
  .sensor-card h3 { color: var(--accent); font-size: 12px; margin-bottom: 8px; }
  .sensor-type { margin-bottom: 6px; }
  .sensor-type .stype { color: var(--info); font-size: 11px; }
  .sensor-type .age { color: var(--dim); font-size: 11px; margin-left: 8px; }
  .sensor-data { color: var(--dim); font-size: 11px; max-height: 120px; overflow-y: auto; white-space: pre-wrap; word-break: break-all; }
  .prompt-layout { flex: 1; display: grid; grid-template-columns: 220px 1fr; gap: 12px; overflow: hidden; }
  .user-list { background: var(--surface); border: 1px solid var(--border); border-radius: 6px; overflow-y: auto; }
  .user-item { padding: 8px 12px; cursor: pointer; border-bottom: 1px solid var(--border); font-size: 12px; }
  .user-item:hover, .user-item.active { background: var(--border); color: var(--accent); }
  .user-item .uid { color: var(--dim); font-size: 10px; display: block; margin-top: 2px; }
  .prompt-detail { display: flex; flex-direction: column; gap: 8px; overflow: hidden; }
  .prompt-meta { font-size: 11px; color: var(--dim); flex-shrink: 0; }
  .prompt-sections { flex: 1; display: grid; grid-template-rows: 1fr 1fr; gap: 8px; overflow: hidden; }
  .prompt-section { display: flex; flex-direction: column; overflow: hidden; }
  .prompt-section h4 { font-size: 11px; color: var(--dim); margin-bottom: 4px; flex-shrink: 0; }
  .prompt-pre { flex: 1; background: var(--surface); border: 1px solid var(--border); border-radius: 4px; padding: 8px; overflow-y: auto; white-space: pre-wrap; word-break: break-all; font-size: 11px; color: var(--text); }
  .badge { display: inline-block; padding: 1px 6px; border-radius: 3px; font-size: 10px; margin-right: 4px; }
  .badge.sl { background: #1e3a5f; color: #60a5fa; }
  .badge.discord { background: #1e2a5f; color: #818cf8; }
  .empty { color: var(--dim); font-size: 12px; padding: 24px; text-align: center; }
</style>
</head>
<body>
<header>
  <h1>✦ Agent Debug</h1>
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
  <div class="sensor-grid" id="sensor-grid"><div class="empty">No sensor data yet.</div></div>
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
  document.getElementById('log-status').innerHTML =
    '● <span id="disconnected">disconnected</span>';
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
  const regions = Object.keys(data);
  if (!regions.length) { grid.innerHTML = '<div class="empty">No sensor data yet.</div>'; return; }
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
  const now = new Date().toLocaleTimeString();
  document.getElementById('sensor-refresh-time').textContent = 'last refresh: ' + now;
  document.getElementById('sensor-age').textContent = 'sensors: ' + now;
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
    const label = uid.replace(/^(discord|sl)_/, '');
    return '<div class="user-item' + (uid === selectedUser ? ' active' : '') +
           '" onclick="selectUser(' + JSON.stringify(uid) + ')">' +
           '<span class="badge ' + badgeCls + '">' + platform + '</span>' +
           esc(label) +
           (ex ? '<span class="uid">' + esc(ex.ts_fmt) + '</span>' : '') +
           '</div>';
  }).join('');
  if (selectedUser && promptData[selectedUser]) renderPromptDetail(selectedUser);
  document.getElementById('prompt-refresh-time').textContent = 'last refresh: ' + new Date().toLocaleTimeString();
}

function selectUser(uid) {
  selectedUser = uid;
  document.querySelectorAll('.user-item').forEach(el => el.classList.remove('active'));
  event.currentTarget.classList.add('active');
  renderPromptDetail(uid);
}

function renderPromptDetail(uid) {
  const d = promptData[uid];
  if (!d) return;
  const ex = d.last_exchange;
  const detail = document.getElementById('prompt-detail');
  detail.innerHTML =
    '<div class="prompt-meta">' +
    (ex ? ex.ts_fmt + ' &nbsp;|&nbsp; ' + ex.platform : 'No exchange yet') + '</div>' +
    '<div class="prompt-sections">' +
    '<div class="prompt-section"><h4>System Prompt</h4>' +
    '<pre class="prompt-pre">' + esc(d.last_prompt || '') + '</pre></div>' +
    '<div class="prompt-section"><h4>Last Exchange</h4>' +
    '<pre class="prompt-pre">' +
    (ex ? esc('USER: ' + ex.user_message + '\\n\\n---\\n\\nREPLY: ' + ex.reply_text) : 'No exchange yet') +
    '</pre></div></div>';
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
