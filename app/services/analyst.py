"""Business logic: performance tracking, 'did it work' verdicts, best-pick scoring.

These functions are called from the admin router and a background bulk job. They talk
to the DB via app.db and the external services (prices, llm).
"""

import json
import logging
import re
from datetime import date, datetime, timezone

from app.config import get_settings
from app.db import connect
from app.services import llm, prices, statuses

logger = logging.getLogger(__name__)

_SEASON_MONTH = {
    "winter": 2,
    "spring": 5,
    "summer": 8,
    "fall": 11,
}


def parse_pitch_date(raw: str | None) -> date | None:
    """Parse a pitch date that may be ISO, "2016-04", or a season like "Spring 2016"."""
    if not raw:
        return None
    s = raw.strip()
    try:
        return date.fromisoformat(s)
    except ValueError:
        pass
    m = re.match(r"^(\d{4})-(\d{1,2})$", s)
    if m:
        return date(int(m.group(1)), int(m.group(2)), 15)
    m = re.search(r"(Winter|Spring|Summer|Fall)?\s*(\d{4})", s, re.IGNORECASE)
    if m:
        year = int(m.group(2))
        month = _SEASON_MONTH.get((m.group(1) or "").lower(), 6)
        return date(year, month, 15)
    return None


async def refresh_idea_performance(idea_id: int, db_path: str | None = None) -> dict:
    """Compute price-based return for one idea and store it in performance."""
    conn = await connect(db_path)
    try:
        row = await conn.execute_fetchall(
            "SELECT * FROM ideas WHERE id = ?", (idea_id,)
        )
        if not row:
            return {"ok": False, "error": "idea not found"}
        idea = row[0]
    finally:
        await conn.close()

    ticker = prices.format_ticker(idea["ticker"]) if idea["ticker"] else None
    if not ticker:
        return {"ok": False, "error": "no ticker"}

    cur_price, as_of = await prices.current_price(ticker)
    if cur_price is None:
        return {"ok": False, "error": "no current price"}

    # Reference price: prefer stated price_at_pitch, else price on pitch_date.
    ref_price = idea["price_at_pitch"]
    pitch_day = parse_pitch_date(idea["pitch_date"]) if ref_price is None else None
    if ref_price is None and pitch_day:
        try:
            ref_price = await prices.price_at(ticker, pitch_day)
        except Exception:  # noqa: BLE001
            ref_price = None

    direction = idea["direction"] or "long"
    if ref_price and cur_price:
        raw = (cur_price - ref_price) / ref_price * 100
        ret = raw if direction != "short" else -raw
    else:
        ret = None

    conn = await connect(db_path)
    try:
        await conn.execute(
            """INSERT INTO performance (idea_id, current_price, as_of, return_pct,
               price_at_ref, source) VALUES (?, ?, ?, ?, ?, ?)""",
            (idea_id, cur_price, as_of, ret, ref_price, "yahoo"),
        )
        await conn.commit()
    finally:
        await conn.close()
    return {"ok": True, "return_pct": ret, "current_price": cur_price, "as_of": as_of}


async def judge_idea_verdict(idea_id: int, db_path: str | None = None) -> dict:
    """Run the LLM verdict for one idea and store it in llm_verdicts (kind='verdict')."""
    conn = await connect(db_path)
    try:
        idea = (await conn.execute_fetchall("SELECT * FROM ideas WHERE id = ?", (idea_id,)))[0]
        perf = await conn.execute_fetchall(
            "SELECT return_pct FROM performance WHERE idea_id = ? ORDER BY id DESC LIMIT 1",
            (idea_id,),
        )
    finally:
        await conn.close()

    ret = perf[0]["return_pct"] if perf else None
    verdict = await llm.judge_idea(idea["thesis"] or "", idea["direction"], ret)
    if not verdict:
        return {"ok": False, "error": "LLM returned nothing"}
    if "verdict" in verdict:
        verdict["return_pct"] = ret

    conn = await connect(db_path)
    try:
        await conn.execute(
            "INSERT INTO llm_verdicts (idea_id, kind, model, content) VALUES (?, 'verdict', ?, ?)",
            (idea_id, get_settings().llm_model, json.dumps(verdict)),
        )
        await conn.commit()
    finally:
        await conn.close()
    return verdict


async def analyze_issue(issue_id: int, db_path: str | None = None) -> dict:
    """Compute performance + verdict for every idea in an issue."""
    conn = await connect(db_path)
    try:
        ideas = await conn.execute_fetchall(
            "SELECT id FROM ideas WHERE issue_id = ?", (issue_id,)
        )
    finally:
        await conn.close()

    results = []
    for row in ideas:
        pid = row["id"]
        perf = await refresh_idea_performance(pid, db_path)
        verdict = await judge_idea_verdict(pid, db_path) if perf.get("ok") else None
        results.append({"idea_id": pid, "performance": perf, "verdict": verdict})

    conn = await connect(db_path)
    try:
        await conn.execute(
            "UPDATE issues SET analyzed_at = ?, status = ?, "
            "updated_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), statuses.ANALYZED,
             datetime.now(timezone.utc).isoformat(), issue_id),
        )
        await conn.commit()
    finally:
        await conn.close()
    return {"issue_id": issue_id, "results": results}


async def score_latest_picks(db_path: str | None = None) -> list[dict]:
    """LLM-rank the freshest issue's ideas for 'best idea today'."""
    conn = await connect(db_path)
    try:
        latest = await conn.execute_fetchall(
            "SELECT id FROM issues ORDER BY COALESCE(issue_number,0) DESC LIMIT 1"
        )
        if not latest:
            return []
        issue_id = latest[0]["id"]
        ideas = await conn.execute_fetchall(
            "SELECT id, ticker, company, direction, thesis, challenge, author "
            "FROM ideas WHERE issue_id = ?",
            (issue_id,),
        )
    finally:
        await conn.close()

    return await score_latest_picks_ideas([dict(r) for r in ideas], issue_id)


async def score_latest_picks_ideas(payload: list[dict], issue_id: int | None = None) -> list[dict]:
    picks = await llm.score_best_picks(payload)
    for p in picks:
        p["issue_id"] = issue_id
    return picks
