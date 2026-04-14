from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)

_SCHEMA_STMTS = [
    """
    CREATE TABLE IF NOT EXISTS sessions (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id    TEXT NOT NULL,
        channel_id TEXT NOT NULL,
        platform   TEXT NOT NULL,
        role       TEXT NOT NULL,
        content    TEXT NOT NULL,
        timestamp  TEXT NOT NULL
    )
    """,
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS sessions_fts
        USING fts5(content, content=sessions, content_rowid=id)
    """,
    """
    CREATE TRIGGER IF NOT EXISTS sessions_ai
        AFTER INSERT ON sessions BEGIN
            INSERT INTO sessions_fts(rowid, content) VALUES (new.id, new.content);
        END
    """,
]

_SEARCH_SQL = """
SELECT s.platform, s.channel_id, s.timestamp, s.role, s.user_id,
       snippet(sessions_fts, 0, '[', ']', '…', 20) AS snippet
FROM sessions_fts
JOIN sessions s ON s.id = sessions_fts.rowid
WHERE sessions_fts MATCH ? AND s.user_id = ?
ORDER BY rank
LIMIT ?
"""


class SessionIndex:
    """SQLite FTS5-backed index of all conversation turns."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        self._init_lock = asyncio.Lock()
        self._ready = False

    async def _ensure_ready(self) -> None:
        if self._ready:
            return
        async with self._init_lock:
            if self._ready:
                return
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
            async with aiosqlite.connect(self._db_path) as db:
                for stmt in _SCHEMA_STMTS:
                    await db.execute(stmt)
                await db.commit()
            self._ready = True

    async def index_turn(
        self,
        user_id: str,
        channel_id: str,
        platform: str,
        role: str,
        content: str,
        timestamp: str,
    ) -> None:
        if not content or not content.strip():
            return
        await self._ensure_ready()
        try:
            async with aiosqlite.connect(self._db_path) as db:
                await db.execute(
                    "INSERT INTO sessions (user_id, channel_id, platform, role, content, timestamp) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (user_id, channel_id, platform, role, content[:4000], timestamp),
                )
                await db.commit()
        except Exception as exc:
            logger.warning("SessionIndex.index_turn failed: %s", exc)

    async def search(self, user_id: str, query: str, limit: int = 5) -> list[dict]:
        await self._ensure_ready()
        try:
            async with aiosqlite.connect(self._db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(_SEARCH_SQL, (query, user_id, limit)) as cur:
                    rows = await cur.fetchall()
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.warning("SessionIndex.search failed: %s", exc)
            return []
