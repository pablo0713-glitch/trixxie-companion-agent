from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).parent.parent
_ENV_PATH = _ROOT / ".env"
_CONFIG_PATH = _ROOT / "data" / "agent_config.json"
_SETUP_DIR = _ROOT / "setup"

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

        return JSONResponse({"env": env_vals, "agent_config": agent_cfg})

    @router.post("/setup/config")
    async def post_config(body: _SetupBody) -> JSONResponse:
        try:
            # Update .env — skip any value that is still the mask
            env_updates = {k: v for k, v in body.env.items() if v != _MASK}
            _write_dotenv(env_updates)

            # Write agent_config.json
            _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            _CONFIG_PATH.write_text(
                json.dumps(body.agent_config, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

            # Invalidate persona cache so changes take effect immediately
            from core.persona import reload_agent_config
            reload_agent_config()

            return JSONResponse({"ok": True})
        except Exception as exc:
            logger.exception("Setup config save failed: %s", exc)
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)

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
