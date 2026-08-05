"""One-off cleanup: merge existing idea fragments already in the DB using the
same rule app/services/dedupe.py now applies at ingest time (see there for
why). Prints a report; only deletes with --apply.

Run: venv/bin/python scripts/dedupe_ideas.py [--apply] [--db-path PATH]
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("dedupe_ideas")

from app.db import connect  # noqa: E402
from app.services.dedupe import fragment_key  # noqa: E402


def group_duplicates(rows: list[dict]) -> list[list[dict]]:
    groups: dict[tuple, list[dict]] = {}
    for row in rows:
        key = fragment_key(
            issue_id=row["issue_id"],
            kind=row["kind"],
            ticker=row["ticker"],
            company=row["company"],
            direction=row["direction"],
            author=row["author"],
        )
        if key is None:
            continue
        groups.setdefault(key, []).append(row)
    return [g for g in groups.values() if len(g) > 1]


def choose_primary(group: list[dict]) -> dict:
    """Prefer a row that already has verdict/performance data attached, then
    the longest (most complete) thesis, then the lowest id as a stable
    tiebreak."""

    def score(row: dict):
        return (
            1 if row["verdict_count"] > 0 else 0,
            1 if row["performance_count"] > 0 else 0,
            len(row.get("thesis") or ""),
            -row["id"],
        )

    return max(group, key=score)


async def main(apply: bool, db_path: str | None) -> None:
    conn = await connect(db_path)
    try:
        ideas = [
            dict(r)
            for r in await conn.execute_fetchall(
                "SELECT id, issue_id, kind, ticker, company, direction, author, thesis FROM ideas"
            )
        ]
        perf_counts = {
            r["idea_id"]: r["n"]
            for r in await conn.execute_fetchall(
                "SELECT idea_id, COUNT(*) as n FROM performance GROUP BY idea_id"
            )
        }
        verdict_counts = {
            r["idea_id"]: r["n"]
            for r in await conn.execute_fetchall(
                "SELECT idea_id, COUNT(*) as n FROM llm_verdicts GROUP BY idea_id"
            )
        }
        for idea in ideas:
            idea["performance_count"] = perf_counts.get(idea["id"], 0)
            idea["verdict_count"] = verdict_counts.get(idea["id"], 0)

        groups = group_duplicates(ideas)
        to_delete: list[int] = []
        for group in groups:
            primary = choose_primary(group)
            losers = [r for r in group if r["id"] != primary["id"]]
            to_delete.extend(r["id"] for r in losers)
            ident = group[0]["ticker"] or group[0]["company"]
            logger.info(
                "issue %s %s: keep %d, delete %s",
                group[0]["issue_id"], ident, primary["id"], [r["id"] for r in losers],
            )

        logger.info(
            "%d duplicate groups, %d rows would be removed (of %d total ideas)",
            len(groups), len(to_delete), len(ideas),
        )

        if not apply:
            logger.info("Dry run only — pass --apply to actually delete.")
            return
        if not to_delete:
            return
        placeholders = ",".join("?" * len(to_delete))
        await conn.execute(f"DELETE FROM ideas WHERE id IN ({placeholders})", to_delete)
        await conn.commit()
        logger.info("Deleted %d duplicate idea rows.", len(to_delete))
    finally:
        await conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="actually delete (default: dry run)")
    parser.add_argument("--db-path", default=None)
    args = parser.parse_args()
    asyncio.run(main(args.apply, args.db_path))
