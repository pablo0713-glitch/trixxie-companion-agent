# Trixxie Carissa — Phase 5 Build Summary
**Date:** 2026-04-07

---

## What Was Built

Phase 5 focused on system prompt efficiency and setup wizard polish. The session delivered Anthropic prompt caching, object deduplication in the sensor context, memory and cross-platform summary caching, owner identity management, platform awareness as a wizard-editable field, a live agent debug panel, and wizard step consolidation.

---

## System Prompt Caching and Size Reduction

**Problem:** The system prompt was ~19,280 chars (~4,264 tokens) and was sent in full on every message, with no caching.

**Solution:** Five changes together reduced per-message payload size significantly.

### 1 — Anthropic prompt caching (`cache_control`)

`build_system_prompt_blocks()` in `core/persona.py` returns a list of Anthropic content blocks instead of a flat string:

- **Block 0 (static):** core identity → platform awareness → memory summary → cross-platform summary → facts. Marked `cache_control: {type: "ephemeral"}`. Re-cached when text changes.
- **Block 1 (dynamic, SL only):** sensor context + recent locations. Never cached — changes every message.

`AnthropicAdapter.create()` accepts `system: str | list`. When a list is passed it adds the `anthropic-beta: prompt-caching-2024-07-31` header automatically. `OllamaAdapter` calls `_flatten_system_blocks()` to merge the list to a plain string — no behaviour change for Ollama users.

### 2 — Object deduplication in sensor context

`_format_sensor_context()` now groups nearby objects by `(name, owner)` pair. Multiple identical objects collapse to a single line:

```
Before: 3 separate lines for the same Hibiscus plant
After:  - Hibiscus A - yellow v2.0 ×3 (3.1m, 5.2m, 8.4m) [scripted] — owner: FloristBot
```

Groups are sorted by minimum distance. First non-empty description wins.

### 3 — Memory notes: compact summary, cached to disk

`AgentCore._load_memory_notes()` now generates a 3–5 bullet summary (≤500 chars) on first use after each consolidation and caches it as `memories_summary_YYYY-MM-DD.md`. Subsequent messages use the cached file. The summary is regenerated only when a new `memories_*.md` file appears (next consolidation cycle). Reduces memory notes from up to 6k chars to ≤500 chars per message.

### 4 — Cross-platform context: cached summary

`AgentCore._load_cross_platform_context()` now generates a 1–3 sentence summary (~200 chars) and caches it per uid in `_cross_summary.txt` (format: `{updated_at}\n{summary}`). The cache is invalidated when `updated_at` changes. Reduces cross-platform context from ~2.5k chars to ~200 chars.

### 5 — Provider compatibility

`_flatten_system_blocks()` in `core/model_adapter.py` merges a content-block list to a plain string. `OllamaAdapter` calls it before every API call — no changes needed in Ollama-specific code paths.

---

## Owner Identity and SL Notes Folder

**Problem:** Memory consolidation notes were saved under the Fedora username (`pablorios/`) and the agent was using that name in its notes.

**Fix:**
- Notes folder is now always `data/notes/SL_Notes/` — independent of the system username.
- `config/settings.py` adds an `owner_name: str` field loaded from `OWNER_NAME` env var.
- Step 1 of the wizard ("Your Agent") includes a "Your Name" field that sets `OWNER_NAME`.
- `interfaces/setup_server.py` runs `_migrate_owner_key()` on every save: renames any non-`SL_Notes` key in `data/person_map.json` to `SL_Notes` and moves the notes folder to match.

---

## Platform Awareness as a Wizard-Editable Field

**Problem:** The `_build_self_awareness_block()` function was hardcoded Python — updating platform behavior required a code deploy. It also had no way to show only the relevant platform's content.

**Fix:**
- `_build_self_awareness_block()` removed entirely from `core/persona.py`.
- `_DEFAULT_CONFIG` now includes a `platform_awareness` dict with keys `discord`, `sl`, `opensim` — each containing the full awareness text.
- `_get_platform_awareness(cfg, platform)` extracts the correct block at runtime, handling both dict and legacy string formats for backwards compatibility.
- Wizard Step 8 ("Context & Platform Awareness") renders one editable textarea per enabled platform. Users can modify the awareness text directly.
- Both `build_system_prompt()` and `build_system_prompt_blocks()` use `_get_platform_awareness()`.

---

## Wizard Step Consolidation (10 → 9 Steps)

**Changes:**
- Old Steps 4 ("Overview & Purpose") + 5 ("Personality") merged into a single Step 4 "Personality & Purpose" — one textarea, "no more than one paragraph" hint.
- `overview` and `purpose` fields removed from `state`, `applyConfig`, the save payload, and `_DEFAULT_CONFIG` in `persona.py`. Existing `agent_config.json` files with these keys continue to render (backwards-compatible reads kept in `_build_core_block()`).
- Old Steps 6–10 renumbered to 5–9.
- Boundaries (Step 5): removed the separate "How to Decline" textarea — the boundary response hint is now in the boundaries text itself. Added "no more than 2–3 sentences" hint.
- Roleplay (Step 6): added "no more than 2–3 sentences" hint.
- Tools (Step 7): added "Tools are used when helpful; the agent does not announce them" to step description.

### Step map (final)

| Step | Name | Content |
|---|---|---|
| 1 | Agent | Agent name + your name |
| 2 | Model | Anthropic or Ollama + max tokens |
| 3 | Platforms | Discord, SL/OpenSim credentials |
| 4 | Personality | Combined persona paragraph |
| 5 | Boundaries | Hard limits (2–3 sentences) |
| 6 | Roleplay | Roleplay rules (2–3 sentences) |
| 7 | Tools | Web search, notes, SL actions |
| 8 | Context | Additional context + per-platform awareness |
| 9 | Save | Review and save |

---

## Agent Debug Page (`/debug`)

A live inspection page at `http://localhost:8080/debug` with three tabs:

| Tab | Content |
|---|---|
| Logs | Real-time Python log stream (SSE). Filter by level and logger. |
| Sensors | Live SensorStore snapshot — raw JSON (left) + formatted plain-text panel (right). Auto-refreshes every 5s. |
| Prompts & Exchanges | Last system prompt + full messages array (JSON) + last exchange per user. Shows char counts per section and total payload size estimate. Auto-refreshes every 10s. |

The Prompts tab exposes both the flat system prompt text and the messages array so prompt size and conversation depth are visible at a glance.

---

## Files Changed

| File | Change |
|---|---|
| `core/persona.py` | Removed `_build_self_awareness_block()`; added `_get_platform_awareness()`; `build_system_prompt_blocks()` returns two-block list; object grouping in `_format_sensor_context()`; `_DEFAULT_CONFIG` consolidated to single `personality` field |
| `core/model_adapter.py` | `system: str \| list` in both adapters; `_flatten_system_blocks()` helper; prompt-caching beta header |
| `core/agent.py` | `_load_memory_notes()` with summary cache; `_load_cross_platform_context()` with `_cross_summary.txt` cache; `_run_tool_loop` uses `list[dict]` system blocks; debug state includes messages array |
| `config/settings.py` | `owner_name` field |
| `interfaces/setup_server.py` | `_migrate_owner_key()`; `_CANONICAL_OWNER = "SL_Notes"` |
| `interfaces/debug_server.py` | `/debug/prompts` exposes messages array; three-section layout with char counts |
| `setup/wizard.js` | 10 → 9 steps; platform_awareness as per-platform dict; owner name field; step consolidation; brevity hints |
| `data/person_map.json` | Key renamed to `SL_Notes` |
| `data/notes/` | Folder renamed `pablorios/` → `SL_Notes/` |
| `lsl/companion_bridge.lsl` | `reply_lc_http` handler in `http_response` for local chat replies |
