from __future__ import annotations

import asyncio
import logging
import os

import uvicorn
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from config.settings import load_settings
from core.agent import AgentCore
from core.model_adapter import create_adapter
from core.rate_limiter import RateLimiter
from core.tools import ToolRegistry
from interfaces.discord_bot.bot import TrixxieBot
from interfaces.debug_server import create_debug_router, install_log_handler
from interfaces.setup_server import create_setup_router
from interfaces.sl_bridge.sensor_store import SensorStore
from interfaces.sl_bridge.server import create_sl_app
from memory.consolidator import MemoryConsolidator
from memory.file_store import FileMemoryStore
from memory.location_store import LocationStore
from memory.person_map import PersonMap

PERSON_MAP_PATH = os.path.join(os.path.dirname(__file__), "data", "person_map.json")
CONSOLIDATION_INTERVAL_SECS = 6 * 3600  # every 6 hours

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    settings = load_settings()

    os.makedirs(settings.memory_dir, exist_ok=True)
    os.makedirs(settings.notes_dir, exist_ok=True)

    memory = FileMemoryStore(settings.memory_dir, settings.memory_max_history)
    sensor_store = SensorStore()
    location_store = LocationStore(settings.memory_dir)
    tool_registry = ToolRegistry(settings)
    rate_limiter = RateLimiter(settings.rate_limit_capacity, settings.rate_limit_refill_rate)
    adapter = create_adapter(settings)

    person_map = PersonMap.load(PERSON_MAP_PATH)
    logger.info("Person map loaded: %d person(s) linked", len(person_map.all_persons()))

    consolidator = MemoryConsolidator(
        adapter=adapter,
        memory_store=memory,
        person_map=person_map,
        notes_dir=settings.notes_dir,
    )

    agent = AgentCore(
        adapter=adapter,
        memory=memory,
        tool_registry=tool_registry,
        rate_limiter=rate_limiter,
        settings=settings,
        person_map=person_map,
    )

    tasks = []

    # ---- Memory consolidation loop ----
    _last_consolidation_path = Path(settings.memory_dir) / ".last_consolidation"

    def _last_consolidation_time() -> float:
        try:
            return float(_last_consolidation_path.read_text().strip())
        except (OSError, ValueError):
            return 0.0

    def _record_consolidation_time() -> None:
        import time
        _last_consolidation_path.write_text(str(time.time()))

    async def consolidation_loop() -> None:
        import time
        # On startup, check how long ago the last run was and sleep only the remainder.
        # This prevents a 6-hour delay after every restart.
        elapsed = time.time() - _last_consolidation_time()
        initial_wait = max(0.0, CONSOLIDATION_INTERVAL_SECS - elapsed)
        if initial_wait < 60:
            initial_wait = 0.0  # overdue — run immediately
        if initial_wait > 0:
            logger.info(
                "Next memory consolidation in %.0f minutes.",
                initial_wait / 60,
            )
        await asyncio.sleep(initial_wait)
        while True:
            logger.info("Running scheduled memory consolidation...")
            await consolidator.run_all()
            _record_consolidation_time()
            await asyncio.sleep(CONSOLIDATION_INTERVAL_SECS)

    tasks.append(asyncio.create_task(consolidation_loop()))

    # ---- Discord bot ----
    if settings.discord_token:
        bot = TrixxieBot(agent, settings)
        tasks.append(asyncio.create_task(bot.start(settings.discord_token)))
        logger.info("Discord bot starting...")
    else:
        logger.warning("DISCORD_TOKEN not set — Discord bot will not start.")

    # ---- Second Life HTTP bridge (always runs) ----
    sl_app = create_sl_app(agent, settings, sensor_store, location_store)

    # ---- Debug page ----
    install_log_handler(asyncio.get_running_loop())
    sl_app.include_router(create_debug_router(sensor_store, agent))

    # ---- Setup wizard ----
    sl_app.include_router(create_setup_router())
    sl_app.mount(
        "/setup/static",
        StaticFiles(directory=str(Path(__file__).parent / "setup")),
        name="setup_static",
    )

    config = uvicorn.Config(
        sl_app,
        host=settings.sl_bridge_host,
        port=settings.sl_bridge_port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    tasks.append(asyncio.create_task(server.serve()))
    logger.info(
        "SL HTTP bridge running at http://%s:%s",
        settings.sl_bridge_host,
        settings.sl_bridge_port,
    )

    if not tasks:
        logger.error("No services started. Check your .env file.")
        return

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
