from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)

_SCHEMA_STMTS = [
    """
    CREATE TABLE IF NOT EXISTS sessions (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id      TEXT NOT NULL,
        channel_id   TEXT NOT NULL,
        platform     TEXT NOT NULL,
        role         TEXT NOT NULL,
        content      TEXT NOT NULL,
        timestamp    TEXT NOT NULL,
        display_name TEXT NOT NULL DEFAULT ''
    )
    """,
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS sessions_fts
        USING fts5(content, display_name, content=sessions, content_rowid=id)
    """,
    """
    CREATE TRIGGER IF NOT EXISTS sessions_ai
        AFTER INSERT ON sessions BEGIN
            INSERT INTO sessions_fts(rowid, content, display_name)
            VALUES (new.id, new.content, new.display_name);
        END
    """,
]

# Migration: run once against existing DBs that predate the display_name column.
_MIGRATE_STMTS = [
    "ALTER TABLE sessions ADD COLUMN display_name TEXT NOT NULL DEFAULT ''",
    "DROP TABLE IF EXISTS sessions_fts",
    "DROP TRIGGER IF EXISTS sessions_ai",
    """
    CREATE VIRTUAL TABLE sessions_fts
        USING fts5(content, display_name, content=sessions, content_rowid=id)
    """,
    """
    CREATE TRIGGER sessions_ai
        AFTER INSERT ON sessions BEGIN
            INSERT INTO sessions_fts(rowid, content, display_name)
            VALUES (new.id, new.content, new.display_name);
        END
    """,
    "INSERT INTO sessions_fts(sessions_fts) VALUES('rebuild')",
]

_SEARCH_SQL = """
SELECT s.platform, s.channel_id, s.timestamp, s.role, s.user_id, s.display_name,
       snippet(sessions_fts, 0, '[', ']', '…', 20) AS snippet
FROM sessions_fts
JOIN sessions s ON s.id = sessions_fts.rowid
WHERE sessions_fts MATCH ?
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

                # Migrate existing DBs that lack the display_name column.
                cols = {row[1] async for row in await db.execute("PRAGMA table_info(sessions)")}
                if "display_name" not in cols:
                    logger.info("SessionIndex: migrating sessions.db to add display_name")
                    for stmt in _MIGRATE_STMTS:
                        try:
                            await db.execute(stmt)
                        except Exception as exc:
                            logger.warning("Migration step failed (may be harmless): %s", exc)
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
        display_name: str = "",
    ) -> None:
        if not content or not content.strip():
            return
        await self._ensure_ready()
        try:
            async with aiosqlite.connect(self._db_path) as db:
                await db.execute(
                    "INSERT INTO sessions "
                    "(user_id, channel_id, platform, role, content, timestamp, display_name) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (user_id, channel_id, platform, role, content[:4000], timestamp, display_name),
                )
                await db.commit()
        except Exception as exc:
            logger.warning("SessionIndex.index_turn failed: %s", exc)

    async def backfill_display_names(self, avatar_map: dict[str, str]) -> None:
        """Set display_name on existing rows where it is empty, using a {user_id: name} map.
        Rebuilds the FTS index afterwards so the names become searchable immediately.
        """
        if not avatar_map:
            return
        await self._ensure_ready()
        try:
            async with aiosqlite.connect(self._db_path) as db:
                for user_id, name in avatar_map.items():
                    await db.execute(
                        "UPDATE sessions SET display_name = ? "
                        "WHERE user_id = ? AND display_name = ''",
                        (name, user_id),
                    )
                await db.commit()
                await db.execute("INSERT INTO sessions_fts(sessions_fts) VALUES('rebuild')")
                await db.commit()
            logger.info("SessionIndex: backfilled display names for %d user(s)", len(avatar_map))
        except Exception as exc:
            logger.warning("SessionIndex.backfill_display_names failed: %s", exc)

    async def query(
        self,
        mode: str,
        date_from: str = "",
        date_to: str = "",
        platform: str = "",
        include_names: list[str] | None = None,
        exclude_names: list[str] | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Structured query against sessions table.

        mode='speakers' — one row per unique person: display_name, platform,
                          first_seen, last_seen, turn_count.
        mode='turns'    — individual message rows with content snippet.
        """
        await self._ensure_ready()

        clauses: list[str] = ["role = 'user'", "display_name != ''"]
        params: list = []

        if date_from:
            clauses.append("timestamp >= ?")
            params.append(date_from)
        if date_to:
            # treat date_to as inclusive end-of-day
            clauses.append("timestamp < ?")
            params.append(date_to + "T23:59:59" if "T" not in date_to else date_to)
        if platform:
            clauses.append("platform = ?")
            params.append(platform)
        if include_names:
            placeholders = ",".join("?" * len(include_names))
            clauses.append(f"display_name IN ({placeholders})")
            params.extend(include_names)
        if exclude_names:
            placeholders = ",".join("?" * len(exclude_names))
            clauses.append(f"display_name NOT IN ({placeholders})")
            params.extend(exclude_names)

        where = " AND ".join(clauses)

        if mode == "speakers":
            sql = (
                f"SELECT display_name, user_id, platform, "
                f"MIN(timestamp) AS first_seen, MAX(timestamp) AS last_seen, COUNT(*) AS turns "
                f"FROM sessions WHERE {where} "
                f"GROUP BY user_id ORDER BY last_seen DESC LIMIT ?"
            )
        else:  # turns
            sql = (
                f"SELECT display_name, user_id, platform, timestamp, "
                f"substr(content, 1, 300) AS snippet "
                f"FROM sessions WHERE {where} "
                f"ORDER BY timestamp DESC LIMIT ?"
            )
        params.append(limit)

        try:
            async with aiosqlite.connect(self._db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(sql, params) as cur:
                    rows = await cur.fetchall()
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.warning("SessionIndex.query failed: %s", exc)
            return []

    async def search(self, query: str, limit: int = 5) -> list[dict]:
        await self._ensure_ready()
        try:
            async with aiosqlite.connect(self._db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(_SEARCH_SQL, (query, limit)) as cur:
                    rows = await cur.fetchall()
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.warning("SessionIndex.search failed: %s", exc)
            return []
