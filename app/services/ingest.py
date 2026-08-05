"""End-to-end ingestion: download a PDF, extract text, split sections, LLM-extract ideas,
and persist them. Used by the admin router and the bulk backfill job."""

import asyncio
import logging
from datetime import datetime, timezone

from app.db import connect
from app.services import downloader, extractor, llm, statuses
from app.services.catalog import CATALOG

logger = logging.getLogger(__name__)

CONCURRENCY = 4


async def run_concurrently(coros, concurrency: int = CONCURRENCY):
    """Run up to `concurrency` coroutines at once, preserving order.

    Shared by scripts/backfill.py and the admin backfill background job.
    """
    sem = asyncio.Semaphore(concurrency)

    async def wrapped(coro):
        async with sem:
            try:
                return await coro
            except Exception as exc:  # noqa: BLE001
                logger.exception("Task failed")
                return {"ok": False, "error": str(exc)}

    return await asyncio.gather(*(wrapped(c) for c in coros))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def ingest_issue(url: str, db_path: str | None = None) -> dict:
    """Download + extract + parse one issue. Returns a summary dict."""
    conn = await connect(db_path)
    try:
        existing = await conn.execute_fetchall(
            "SELECT id, status FROM issues WHERE source_url = ?", (url,)
        )
        if existing:
            issue_id = existing[0]["id"]
            status = existing[0]["status"]
            # Allow retry of incomplete/failed downloads; treat parsed/analyzed as done.
            if status in statuses.DONE:
                return {"ok": False, "error": "issue already ingested", "issue_id": issue_id}
            # Reset the stale row so we can retry.
            await conn.execute("DELETE FROM issues WHERE id = ?", (issue_id,))
            await conn.commit()
        await conn.execute(
            "INSERT INTO issues (source_url, title, season, issue_number, status) "
            "VALUES (?, ?, ?, ?, ?)",
            (url, CATALOG.get(url, {}).get("title", "Untitled"), CATALOG.get(url, {}).get("season"),
             CATALOG.get(url, {}).get("issue_number"), statuses.DOWNLOADING),
        )
        await conn.commit()
        issue_id = (await conn.execute_fetchall("SELECT last_insert_rowid() AS id"))[0]["id"]
    finally:
        await conn.close()

    filename = await downloader.download_pdf(url)
    if not filename:
        await _set_status(issue_id, statuses.DOWNLOAD_FAILED, db_path)
        return {"ok": False, "error": "download failed", "issue_id": issue_id}

    from pathlib import Path
    from app.config import get_settings
    pdf_path = Path(get_settings().pdf_dir) / filename

    text = extractor.extract_pdf_text(pdf_path)
    if not text.strip():
        await _set_status(issue_id, statuses.EXTRACT_FAILED, db_path)
        return {"ok": False, "error": "empty text", "issue_id": issue_id}

    sections = extractor.split_sections(text)
    # Pre-filter: only send passages that plausibly name an investment idea.
    candidate_sections = [s for s in sections if extractor.has_idea_signal(s["text"])]
    pitch_sections = [s for s in candidate_sections if s["is_pitch"]]
    interview_sections = [s for s in candidate_sections if not s["is_pitch"]]

    # Process pitch sections first (higher signal), then interviews.
    ideas: list[dict] = []
    for section in pitch_sections + interview_sections:
        found = await llm.extract_ideas(section["text"])
        for idea in found:
            if idea.get("ticker") or idea.get("company"):
                ideas.append(idea)

    conn = await connect(db_path)
    try:
        # Ideas insert and the status flip to 'parsed' commit together: a crash
        # between the two used to leave the issue stuck at a DB-visible
        # 'extracted' status with ideas already present but never re-attempted.
        # Now a crash here leaves the last real commit ('downloading'), so a
        # retry cleanly deletes-and-redoes instead.
        await conn.execute(
            "UPDATE issues SET pdf_path = ?, status = ?, extracted_at = ?, updated_at = ? "
            "WHERE id = ?",
            (filename, statuses.PARSED, _now(), _now(), issue_id),
        )
        for idea in ideas:
            await conn.execute(
                """INSERT INTO ideas (issue_id, kind, ticker, company, direction, thesis,
                   challenge, author, price_at_pitch, pitch_date, target_price)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (issue_id, idea.get("kind", "position"), idea.get("ticker"),
                 idea.get("company"), idea.get("direction"), idea.get("thesis"),
                 idea.get("challenge"), idea.get("author"), idea.get("price_at_pitch"),
                 idea.get("pitch_date"), idea.get("target_price")),
            )
        await conn.commit()
    finally:
        await conn.close()

    return {"ok": True, "issue_id": issue_id, "ideas": len(ideas)}


async def _set_status(issue_id: int, status: str, db_path: str | None) -> None:
    conn = await connect(db_path)
    try:
        await conn.execute(
            "UPDATE issues SET status = ?, updated_at = ? WHERE id = ?",
            (status, _now(), issue_id),
        )
        await conn.commit()
    finally:
        await conn.close()
