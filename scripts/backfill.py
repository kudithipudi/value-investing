"""Bulk backfill: ingest every catalog issue not yet in the DB, then analyze all.

Resumable: skips issues already parsed/analyzed. Run from project root as:
    venv/bin/python scripts/backfill.py [--analyze] [--picks]
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("backfill")

from app.config import get_settings  # noqa: E402
from app.db import connect  # noqa: E402
from app.services import analyst, ingest  # noqa: E402
from app.services.catalog import KNOWN_ISSUES  # noqa: E402
from app.services.ingest import CONCURRENCY, run_concurrently  # noqa: E402


async def ingest_missing() -> list[dict]:
    conn = await connect()
    try:
        existing = {
            r["source_url"]: r["status"]
            for r in await conn.execute_fetchall("SELECT source_url, status FROM issues")
        }
    finally:
        await conn.close()

    jobs = []
    for season, num, title, url in KNOWN_ISSUES:
        status = existing.get(url)
        if status in ("parsed", "extracted", "analyzed"):
            continue
        jobs.append((url, status))
    logger.info("Ingesting %d missing issues", len(jobs))
    results = await run_concurrently(
        [ingest.ingest_issue(url) for url, _ in jobs], CONCURRENCY
    )
    return [{"url": url, **r} for (url, _), r in zip(jobs, results)]


async def analyze_all() -> dict:
    conn = await connect()
    try:
        parsed = await conn.execute_fetchall(
            "SELECT id FROM issues WHERE status IN ('parsed','extracted')"
        )
    finally:
        await conn.close()

    summary = {"issues": len(parsed), "ok": 0, "failed": []}
    results = await run_concurrently(
        [analyst.analyze_issue(row["id"]) for row in parsed], CONCURRENCY
    )
    for row, r in zip(parsed, results):
        if isinstance(r, dict) and "results" in r:
            summary["ok"] += 1
            logger.info("Analyzed issue %d", row["id"])
        else:
            summary["failed"].append({"issue": row["id"], "error": r.get("error")})
    return summary


async def score_latest() -> dict:
    picks = await analyst.score_latest_picks()
    conn = await connect()
    try:
        latest = await conn.execute_fetchall(
            "SELECT id FROM issues ORDER BY COALESCE(issue_number,0) DESC LIMIT 1"
        )
        issue_id = latest[0]["id"] if latest else None
        if picks and issue_id:
            await conn.execute(
                """DELETE FROM llm_verdicts WHERE kind = 'best_pick' AND idea_id IN
                   (SELECT id FROM ideas WHERE issue_id = ?)""",
                (issue_id,),
            )
            for p in picks:
                match = await conn.execute_fetchall(
                    "SELECT id FROM ideas WHERE issue_id = ? AND ticker = ? LIMIT 1",
                    (issue_id, p.get("ticker")),
                )
                if not match:
                    continue
                await conn.execute(
                    "INSERT INTO llm_verdicts (idea_id, kind, model, content) VALUES (?, 'best_pick', ?, ?)",
                    (match[0]["id"], get_settings().llm_model, json.dumps(p)),
                )
            await conn.commit()
    finally:
        await conn.close()
    return {"picks": len(picks)}


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--analyze", action="store_true", help="analyze parsed issues")
    parser.add_argument("--picks", action="store_true", help="score best picks for latest issue")
    args = parser.parse_args()

    results = await ingest_missing()
    ok = sum(1 for r in results if r.get("ok"))
    logger.info("Ingest: %d/%d ok", ok, len(results))
    for r in results:
        if not r.get("ok"):
            logger.warning("Failed: %s %s", r["url"].split("/")[-1], r.get("error"))

    if args.analyze:
        summary = await analyze_all()
        logger.info("Analyze: %d issues, %d ok, %d failed", summary["issues"], summary["ok"], len(summary["failed"]))

    if args.picks:
        picks = await score_latest()
        logger.info("Best picks scored: %d", picks["picks"])


if __name__ == "__main__":
    asyncio.run(main())
    sys.exit(0)
