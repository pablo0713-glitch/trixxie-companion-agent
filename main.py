from __future__ import annotations

import asyncio
import logging
import os

import anthropic
import uvicorn

from config.settings import load_settings
from core.agent import AgentCore
from core.rate_limiter import RateLimiter
from core.tools import ToolRegistry
from interfaces.discord_bot.bot import TrixxieBot
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
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    person_map = PersonMap.load(PERSON_MAP_PATH)
    logger.info("Person map loaded: %d person(s) linked", len(person_map.all_persons()))

    consolidator = MemoryConsolidator(
        client=client,
        memory_store=memory,
        person_map=person_map,
        notes_dir=settings.notes_dir,
        model=settings.claude_model,
    )

    agent = AgentCore(
        client=client,
        memory=memory,
        tool_registry=tool_registry,
        rate_limiter=rate_limiter,
        settings=settings,
        person_map=person_map,
    )

    tasks = []

    # ---- Memory consolidation loop ----
    async def consolidation_loop() -> None:
        while True:
            await asyncio.sleep(CONSOLIDATION_INTERVAL_SECS)
            logger.info("Running scheduled memory consolidation...")
            await consolidator.run_all()

    tasks.append(asyncio.create_task(consolidation_loop()))

    # ---- Discord bot ----
    if settings.discord_token:
        bot = TrixxieBot(agent, settings)
        tasks.append(asyncio.create_task(bot.start(settings.discord_token)))
        logger.info("Discord bot starting...")
    else:
        logger.warning("DISCORD_TOKEN not set — Discord bot will not start.")

    # ---- Second Life HTTP bridge (always runs — used by Trixxie's in-world HUD) ----
    sl_app = create_sl_app(agent, settings, sensor_store, location_store)
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
