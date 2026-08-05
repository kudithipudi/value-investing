import logging
from pathlib import Path

import aiosqlite

from app.config import get_settings

logger = logging.getLogger(__name__)

_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "db" / "schema.sql"


async def connect(db_path: str | None = None) -> aiosqlite.Connection:
    db_path = db_path or get_settings().db_path
    conn = await aiosqlite.connect(db_path)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA foreign_keys=ON")
    return conn


async def init_db(db_path: str | None = None) -> None:
    conn = await connect(db_path)
    try:
        schema = _SCHEMA_PATH.read_text()
        await conn.executescript(schema)
        await conn.commit()
        await _migrate(conn)
        logger.info("Database schema applied")
    finally:
        await conn.close()


async def _migrate(conn: aiosqlite.Connection) -> None:
    """Additive column migrations that `CREATE TABLE IF NOT EXISTS` can't
    express — it only creates tables that don't exist yet, not columns
    missing from a table that already does."""
    cols = {row["name"] for row in await conn.execute_fetchall("PRAGMA table_info(performance)")}
    if "currency" not in cols:
        await conn.execute("ALTER TABLE performance ADD COLUMN currency TEXT")
        await conn.commit()
        logger.info("Migrated: added performance.currency")


async def get_db():
    conn = await connect()
    try:
        yield conn
    finally:
        await conn.close()
