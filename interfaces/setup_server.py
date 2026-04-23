from __future__ import annotations

import json
import logging
import re
import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).parent.parent
_ENV_PATH = _ROOT / ".env"
_CONFIG_PATH = _ROOT / "data" / "agent_config.json"
_IDENTITY_DIR = _ROOT / "data" / "identity"
_SETUP_DIR = _ROOT / "setup"

_PERSON_MAP_PATH = _ROOT / "data" / "person_map.json"
_NOTES_DIR = _ROOT / "data" / "notes"
_CANONICAL_OWNER = "SL_Notes"

_SENSITIVE_KEYS = {
    "ANTHROPIC_API_KEY",
    "DISCORD_TOKEN",
    "SL_BOT_PASSWORD",
    "SL_BRIDGE_SECRET",
    "SEARCH_API_KEY",
}
_MASK = "••••••••"


class _SetupBody(BaseModel):
    env: dict[str, str]
    agent_config: dict[str, Any]


class _ScriptUpdateBody(BaseModel):
    url: str
    secret: str
    triggers: list[str]
    opensim: bool = False


def _patch_scripts(url: str, secret: str, grid: str, triggers: list[str]) -> dict[str, str]:
    """Patch SERVER_URL / SECRET / GRID / TRIGGER_NAMES into the LSL and Lua scripts."""
    lsl_path = _ROOT / "lsl" / "companion_bridge.lsl"
    lua_path = _ROOT / "lua" / "agent_companion.lua"
    triggers_lsl = ", ".join(f'"{t}"' for t in triggers if t)
    results: dict[str, str] = {}

    def _sub(pattern: str, value: str, text: str) -> str:
        return re.sub(pattern, lambda m: m.group(1) + value + m.group(2), text)

    if lsl_path.exists():
        try:
            text = lsl_path.read_text(encoding="utf-8")
            text = _sub(r'(string\s+SERVER_URL\s*=\s*")[^"]*(")', url, text)
            text = _sub(r'(string\s+SECRET\s*=\s*")[^"]*(")', secret, text)
            text = _sub(r'(string\s+GRID\s*=\s*")[^"]*(")', grid, text)
            text = re.sub(
                r'(list\s+TRIGGER_NAMES\s*=\s*\[)[^\]]*(\])',
                lambda m: m.group(1) + triggers_lsl + m.group(2),
                text,
            )
            lsl_path.write_text(text, encoding="utf-8")
            results["lsl"] = "ok"
        except Exception as exc:
            results["lsl"] = str(exc)
    else:
        results["lsl"] = "not found"

    if lua_path.exists():
        try:
            text = lua_path.read_text(encoding="utf-8")
            text = _sub(r'(local\s+SERVER_URL\s*=\s*")[^"]*(")', url, text)
            text = _sub(r'(local\s+SECRET\s*=\s*")[^"]*(")', secret, text)
            text = _sub(r'(local\s+GRID\s*=\s*")[^"]*(")', grid, text)
            lua_path.write_text(text, encoding="utf-8")
            results["lua"] = "ok"
        except Exception as exc:
            results["lua"] = str(exc)
    else:
        results["lua"] = "not found"

    return results


def patch_scripts_from_env() -> None:
    """Read SL config from .env and patch both scripts. Called on every startup."""
    env = _read_dotenv()
    url = env.get("SL_BRIDGE_URL", "")
    if not url:
        return  # SL not configured — nothing to patch
    secret = env.get("SL_BRIDGE_SECRET", "")
    opensim = env.get("OPENSIM_ENABLED", "false").lower() == "true"
    grid = "opensim" if opensim else "sl"
    triggers_raw = env.get("SL_TRIGGER_NAMES", "")
    triggers = [t.strip() for t in triggers_raw.split(",") if t.strip()]
    results = _patch_scripts(url, secret, grid, triggers)
    logger.info("Script patch on startup: %s", results)


def create_setup_router() -> APIRouter:
    router = APIRouter()

    @router.get("/setup")
    async def setup_index() -> FileResponse:
        return FileResponse(str(_SETUP_DIR / "index.html"))

    @router.get("/setup/status")
    async def setup_status() -> JSONResponse:
        configured = _CONFIG_PATH.exists()
        agent_name = "Agent"
        if configured:
            try:
                cfg = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
                agent_name = cfg.get("agent_name", "Agent")
            except Exception:
                pass
        return JSONResponse({"configured": configured, "agent_name": agent_name})

    @router.get("/setup/config")
    async def get_config() -> JSONResponse:
        env_vals = _read_dotenv()
        for key in _SENSITIVE_KEYS:
            if env_vals.get(key):
                env_vals[key] = _MASK

        agent_cfg: dict = {}
        if _CONFIG_PATH.exists():
            try:
                agent_cfg = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass

        if not agent_cfg:
            from core.persona import get_default_config
            agent_cfg = get_default_config()

        # Load identity files (agent.md, soul.md, user.md)
        from core.persona import get_default_identity
        defaults = get_default_identity()
        identity: dict[str, str] = {}
        for fname in ("agent.md", "soul.md", "user.md"):
            key = fname.replace(".", "_")  # agent_md, soul_md, user_md
            fpath = _IDENTITY_DIR / fname
            identity[key] = fpath.read_text(encoding="utf-8") if fpath.exists() else ""

        agent_cfg["identity"] = identity

        return JSONResponse({"env": env_vals, "agent_config": agent_cfg})

    @router.post("/setup/config")
    async def post_config(body: _SetupBody) -> JSONResponse:
        try:
            # Update .env — skip any value that is still the mask
            env_updates = {k: v for k, v in body.env.items() if v != _MASK}
            _write_dotenv(env_updates)

            # Write identity files (agent.md, soul.md, user.md) if provided
            identity = body.agent_config.pop("identity", None)
            if isinstance(identity, dict):
                _IDENTITY_DIR.mkdir(parents=True, exist_ok=True)
                from core.persona import get_default_identity
                defaults = get_default_identity()
                for fname in ("agent.md", "soul.md", "user.md"):
                    key = fname.replace(".", "_")
                    content = identity.get(key, "").strip()
                    if not content:
                        content = defaults.get(fname, "")
                    (_IDENTITY_DIR / fname).write_text(content, encoding="utf-8")

            # Write agent_config.json
            _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            _CONFIG_PATH.write_text(
                json.dumps(body.agent_config, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

            # Migrate person_map.json key → SL_Notes and rename notes folder
            _migrate_owner_key()

            # Invalidate persona cache so changes take effect immediately
            from core.persona import reload_agent_config
            reload_agent_config()

            return JSONResponse({"ok": True})
        except Exception as exc:
            logger.exception("Setup config save failed: %s", exc)
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)

    @router.post("/setup/update-scripts")
    async def update_scripts(body: _ScriptUpdateBody) -> JSONResponse:
        grid = "opensim" if body.opensim else "sl"
        results = _patch_scripts(body.url, body.secret, grid, body.triggers)
        ok = all(v == "ok" for v in results.values())
        return JSONResponse({"ok": ok, "results": results})

    return router


# ------------------------------------------------------------------ .env helpers

def _read_dotenv() -> dict[str, str]:
    result: dict[str, str] = {}
    if not _ENV_PATH.exists():
        return result
    for line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, val = stripped.partition("=")
        result[key.strip()] = val.strip()
    return result


def _migrate_owner_key() -> None:
    """Rename any non-SL_Notes key in person_map.json to SL_Notes, move notes folder."""
    if not _PERSON_MAP_PATH.exists():
        return
    try:
        data: dict = json.loads(_PERSON_MAP_PATH.read_text(encoding="utf-8"))
    except Exception:
        return
    old_keys = [k for k in data if k != _CANONICAL_OWNER]
    if not old_keys:
        return  # already correct or empty
    new_data: dict = {_CANONICAL_OWNER: data.get(_CANONICAL_OWNER, [])}
    for old_key in old_keys:
        # Merge user_ids (avoid duplicates)
        for uid in data[old_key]:
            if uid not in new_data[_CANONICAL_OWNER]:
                new_data[_CANONICAL_OWNER].append(uid)
        # Rename notes folder if it exists
        old_folder = _NOTES_DIR / old_key
        new_folder = _NOTES_DIR / _CANONICAL_OWNER
        if old_folder.exists() and not new_folder.exists():
            shutil.move(str(old_folder), str(new_folder))
        elif old_folder.exists() and new_folder.exists():
            # Both exist: move files from old into new (don't overwrite)
            for f in old_folder.iterdir():
                dest = new_folder / f.name
                if not dest.exists():
                    shutil.move(str(f), str(dest))
            shutil.rmtree(str(old_folder), ignore_errors=True)
    _PERSON_MAP_PATH.write_text(
        json.dumps(new_data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    logger.info("Migrated person_map keys %s → %s", old_keys, _CANONICAL_OWNER)


def _write_dotenv(updates: dict[str, str]) -> None:
    existing_keys: set[str] = set()
    lines: list[str] = []

    if _ENV_PATH.exists():
        for line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                key = stripped.split("=", 1)[0].strip()
                existing_keys.add(key)
                if key in updates:
                    lines.append(f"{key}={updates[key]}")
                else:
                    lines.append(line)
            else:
                lines.append(line)

    for key, val in updates.items():
        if key not in existing_keys:
            lines.append(f"{key}={val}")

    _ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
