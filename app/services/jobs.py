"""Background job tracking on top of the (previously unused) analysis_runs table.

Used to give the admin UI a pollable status for the long-running backfill and
analyze actions, instead of blocking the request until they finish.
"""

import json
import logging
from datetime import datetime, timezone

from app.db import connect

logger = logging.getLogger(__name__)

TERMINAL = ("done", "failed")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def create_job(kind: str, note: dict | None = None, db_path: str | None = None) -> int:
    conn = await connect(db_path)
    try:
        await conn.execute(
            "INSERT INTO analysis_runs (kind, status, started_at, note) VALUES (?, 'running', ?, ?)",
            (kind, _now(), json.dumps(note or {})),
        )
        await conn.commit()
        row = await conn.execute_fetchall("SELECT last_insert_rowid() AS id")
        return row[0]["id"]
    finally:
        await conn.close()


async def update_job(
    job_id: int,
    *,
    status: str | None = None,
    note: dict | None = None,
    db_path: str | None = None,
) -> None:
    conn = await connect(db_path)
    try:
        sets, params = [], []
        if status is not None:
            sets.append("status = ?")
            params.append(status)
            if status in TERMINAL:
                sets.append("finished_at = ?")
                params.append(_now())
        if note is not None:
            sets.append("note = ?")
            params.append(json.dumps(note))
        if not sets:
            return
        params.append(job_id)
        await conn.execute(f"UPDATE analysis_runs SET {', '.join(sets)} WHERE id = ?", params)
        await conn.commit()
    finally:
        await conn.close()


async def get_latest_job(kind: str, db_path: str | None = None) -> dict | None:
    conn = await connect(db_path)
    try:
        rows = await conn.execute_fetchall(
            "SELECT * FROM analysis_runs WHERE kind = ? ORDER BY id DESC LIMIT 1", (kind,)
        )
    finally:
        await conn.close()
    if not rows:
        return None
    job = dict(rows[0])
    try:
        job["note"] = json.loads(job.get("note") or "{}")
    except json.JSONDecodeError:
        job["note"] = {}
    return job


async def is_job_running(kind: str, db_path: str | None = None) -> bool:
    job = await get_latest_job(kind, db_path)
    return bool(job and job["status"] == "running")
