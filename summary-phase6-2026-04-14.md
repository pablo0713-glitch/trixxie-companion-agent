# Trixxie Carissa — Phase 6 Build Summary
**Date:** 2026-04-14

---

## What Was Built

Phase 6 restructured the agent's identity and memory systems around the Hermes Agent architecture — replacing flat persona config fields and auto-generated summaries with agent-curated, bounded memory files, and adding full-text search over the entire conversation history. Three sub-phases were delivered in one session.

---

## Phase A — Identity Files

**Problem:** Persona text was stored as flat fields in `agent_config.json` — a single blob with no separation of role, tone, or owner context. Editing required navigating a wall of JSON keys in the wizard.

**Solution:** Three dedicated markdown files in `data/identity/`:

| File | Content |
|---|---|
| `agent.md` | Role, purpose, behaviors, hard boundaries, RP rules |
| `soul.md` | Tone, humor, quirks, conversational style |
| `user.md` | Owner profile (single user) |

`_load_identity_files()` in `core/persona.py` reads and joins them on load, falling back to `_build_core_block(cfg)` if the files don't exist (backwards compatible). `get_default_identity()` provides starter content so new installs get a sensible default.

### Wizard refactor: 9 → 7 steps

Steps 5 (Boundaries) and 6 (Roleplay) were removed — their content moved into `agent.md`. Step 4 became "Identity" with three labeled textareas. Total: 7 steps.

| Step | Name | Content |
|---|---|---|
| 1 | Agent | Agent name + your name |
| 2 | Model | Anthropic or Ollama + max tokens |
| 3 | Platforms | Discord, SL/OpenSim credentials |
| 4 | Identity | agent.md, soul.md, user.md textareas |
| 5 | Tools | Web search, notes, SL actions |
| 6 | Context | Additional context + per-platform awareness |
| 7 | Save | Review and save |

`interfaces/setup_server.py` reads and writes the three files on `GET /setup/config` and `POST /setup/config`.

---

## Phase B — Hermes-Style Curated Memory

**Problem:** Memory was a mix of auto-generated markdown summaries and cached cross-platform context snippets — the agent had no direct control over what it remembered. The system injected ~6k chars of loosely structured notes with no size guarantee.

**Solution:** Two bounded, agent-curated files per canonical `person_id`:

| File | Cap | Content |
|---|---|---|
| `MEMORY.md` | ~2,000 chars | Context, facts, notes about the world |
| `USER.md` | ~1,200 chars | Owner preferences, communication style |

Both use `§`-delimited entries managed by the `memory` tool (add / replace / remove actions). The agent decides in real time what's worth keeping, rewording, or dropping.

### New `memory` tool

`core/tool_handlers/memory.py` — available on all platforms. Parameters:

```
action:   "add" | "replace" | "remove"
store:    "memory" | "user"
text:     entry text (required for add)
old_text: substring to match (required for replace/remove)
```

Entries are trimmed to cap (oldest removed first) after each write.

### Injection format (Hermes-aligned)

```
MEMORY (agent's notes) [42% — 840/2,000 chars]
§
User prefers short replies in-world.
§
StonedGrits owns the Nakano sim.

USER (owner profile) [61% — 732/1,200 chars]
§
Pablo, goes by StonedGrits in SL. Builder and sim owner.
```

Loaded **frozen** at the start of `handle_message()` and placed in **Block 0** (cached). Changes made by the `memory` tool mid-session take effect on the next message. Falls back to `_facts.json` if `MEMORY.md` is absent (legacy transition path).

### Short-term memory bridge (STM)

After every exchange, `_append_stm_entry()` fires as a background task. It calls `create_simple()` to produce a 1–2 sentence third-person summary (max 120 chars) and appends it to `data/memory/{safe_uid}/stm.json` — rolling 10 entries.

STM is only injected into **Block 1** for **linked** platform UIDs (cross-platform bridge). The current conversation's own history is already in the messages array.

### Consolidator rewrite

`MemoryConsolidator._consolidate()` now:
1. Extracts bullet points from Claude's generated notes
2. Appends each bullet to `MEMORY.md` via `_add_entry()`, trimming oldest to maintain cap
3. Keeps the full text as a markdown audit trail at `data/notes/SL_Notes/memories_YYYY-MM-DD.md`

Removed: `_load_memory_notes()`, `memories_summary_*.md`, `_load_cross_platform_context()`, `_cross_summary.txt`.

### Block structure after Phase B

**Block 0 — static, cached:**
```
identity files → platform awareness → additional context → MEMORY.md + USER.md
```

**Block 1 — dynamic, no cache:**
```
STM bridge (linked uids) → sensor context (SL) → recent locations (SL)
```

---

## Phase C — Session Search (SQLite FTS5)

**Problem:** Past conversations were fully inaccessible mid-reply unless they happened to be in the current history window or the consolidator had picked them up.

**Solution:** SQLite FTS5 full-text index over all conversation turns.

### `memory/session_index.py`

`SessionIndex` — lazy-init SQLite database at `data/memory/sessions.db`.

```sql
CREATE TABLE sessions (id, user_id, channel_id, platform, role, content, timestamp);
CREATE VIRTUAL TABLE sessions_fts USING fts5(content, content=sessions, content_rowid=id);
CREATE TRIGGER sessions_ai AFTER INSERT ON sessions BEGIN
    INSERT INTO sessions_fts(rowid, content) VALUES (new.id, new.content);
END;
```

- `index_turn(user_id, channel_id, platform, role, content, timestamp)` — insert + trigger FTS update
- `search(user_id, query, limit=5)` — FTS5 ranked search scoped to one user; returns platform, date, role, FTS snippet

### `session_search` tool

`core/tool_handlers/session_search.py` wraps `SessionIndex.search()`. Returns formatted snippets:

```
[DISCORD | 2026-04-10 | assistant] "The [Botanical] sim has great atmosphere for..."
```

Available on all platforms when `SessionIndex` is wired up.

### Automatic indexing

`FileMemoryStore.append_turn()` now fires `session_index.index_turn()` as a background `asyncio.create_task` after each write. Plain text is extracted from content block lists via `_text_from_content()`.

---

## Bug Fixes

### STM append — assistant prefill error

`_append_stm_entry()` was sending a messages array ending with `role: assistant`, which Claude 4.x rejects ("This model does not support assistant message prefill"). Fixed by folding the exchange into the user message body:

```python
# Before — ended with assistant turn → 400 Bad Request
messages=[
    {"role": "user", "content": user_message},
    {"role": "assistant", "content": reply_text},
]

# After — single user turn containing the exchange
messages=[{
    "role": "user",
    "content": f"Summarize...\n\nUser: {user_message}\n\nAssistant: {reply_text}"
}]
```

### `_load_memory_files()` — raw slice on cap enforcement

`_load_memory_files()` in `core/agent.py` enforced the char cap via `content[:cap]` — a raw character slice that could split an entry mid-sentence. Fixed by calling `_trim_to_cap()` (same entry-aware function used by the `memory` tool write path), which drops oldest `§` entries until the file fits. Symptom: the debug panel's MEMORY section showed only the first entry (61 chars) with the remaining ~1,900 chars silently intact but unsplit.

---

### SessionIndex schema init — incomplete input

`_ensure_ready()` split the schema on `;` to execute statements individually. The `CREATE TRIGGER ... BEGIN ... END;` statement contains an inner semicolon, so splitting produced a truncated fragment (`incomplete input` from SQLite). Fixed by replacing the single string + split approach with an explicit list of statement strings.

---

## Memory Security Scanner

Memory entries (MEMORY.md and USER.md) are injected into Block 0 of the system prompt on every message. A compromised entry is a prompt injection. `_scan_entry(text)` in `core/tool_handlers/memory.py` checks every `add` and `replace` call before writing. The consolidator path is also guarded.

### What is scanned

| Category | Patterns |
|---|---|
| Prompt injection | "ignore previous/all instructions", "you are now", "act as", "new instructions:", "[system]", "jailbreak", "DAN mode", "override your", "forget everything" |
| Credential exfiltration | `sk-<20+ chars>` (API keys), `AKIA<16 chars>` (AWS), `Bearer <long token>`, `-----BEGIN RSA/EC/OPENSSH/DSA/PGP PRIVATE` |
| Exfiltration with destination | "exfiltrate ... to https://...", "send my keys to <IP>" — requires action + destination, not bare keyword |
| Shell injection | Backtick execution `` `cmd` ``, subshell `$(cmd)` |
| Invisible Unicode | Zero-width spaces, directional overrides (U+202E RTL, etc.), BOM, soft hyphens |

Blocked writes log a `WARNING` with person_id and the first 80 chars of the offending text. The rejection reason is returned to the tool caller. `remove` is not scanned — removing is always safe.

**Design note:** Text-intent patterns (bare "exfiltrate", "credential") were intentionally excluded after producing false positives when the agent discussed the security system in conversation. All retained patterns are structural (key format shapes, shell syntax, Unicode codepoints) or require explicit action + destination context.

---

## Files Changed

| File | Change |
|---|---|
| `data/identity/agent.md` | New — created on first wizard save |
| `data/identity/soul.md` | New — created on first wizard save |
| `data/identity/user.md` | New — created on first wizard save |
| `core/persona.py` | `_load_identity_files()`, `_DEFAULT_IDENTITY`, `get_default_identity()`; `person_id` added to `MessageContext`; `build_system_prompt_blocks()` uses identity files + memory_files + stm_bridge |
| `core/agent.py` | `_load_memory_files()`, `_load_stm_bridge()`, `_append_stm_entry()`; removed `_load_memory_notes()` and `_load_cross_platform_context()` |
| `core/tools.py` | `MEMORY_SCHEMA`, `SESSION_SEARCH_SCHEMA`; `ToolRegistry` accepts `session_index`; both tools registered in dispatch |
| `core/tool_handlers/memory.py` | New — `handle_memory()` with `_entries()`, `_join_entries()`, `_add_entry()`, `_remove_entry()`, `_replace_entry()`, `_trim_to_cap()` |
| `core/tool_handlers/session_search.py` | New — `handle_session_search()` wrapping `SessionIndex.search()` |
| `memory/consolidator.py` | `_consolidate()` appends bullets to `MEMORY.md` (§-delimited, capped); keeps markdown audit trail |
| `memory/session_index.py` | New — `SessionIndex` with lazy-init FTS5 schema, `index_turn()`, `search()` |
| `memory/file_store.py` | Accepts `session_index`; `append_turn()` fires `index_turn()` background task; `_text_from_content()` helper |
| `interfaces/setup_server.py` | Reads/writes `data/identity/*.md`; `get_default_identity()` for empty fields |
| `setup/wizard.js` | 9→7 steps; Step 4 "Identity" with three textareas; removed Boundaries + Roleplay steps; renumbered |
| `main.py` | Instantiates `SessionIndex`; passes to `FileMemoryStore` and `ToolRegistry` |
| `requirements.txt` | Added `aiosqlite>=0.20.0` |
| `core/agent.py` | Fixed STM append — messages array now ends with user turn |
| `core/agent.py` | Fixed `_load_memory_files()` cap — `_trim_to_cap()` replaces raw `content[:cap]` slice |
| `memory/session_index.py` | Fixed schema init — list of statements replaces split-on-semicolon |
