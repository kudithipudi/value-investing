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
        logger.info("Database schema applied")
    finally:
        await conn.close()


async def get_db():
    conn = await connect()
    try:
        yield conn
    finally:
        await conn.close()
