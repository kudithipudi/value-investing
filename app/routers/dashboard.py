import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.db import get_db
from app.services import prices

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["prefix"] = get_settings().root_path

PAGE_SIZE = 24

# "Latest row per idea" via window functions instead of relying on SQLite's
# non-standard bare-GROUP_BY row selection. Shared by _highlights(),
# issue_detail(), and the /ideas search route below.
_IDEA_CTE = """
WITH latest_perf AS (
  SELECT idea_id, current_price, return_pct, as_of,
         ROW_NUMBER() OVER (PARTITION BY idea_id ORDER BY id DESC) AS rn
  FROM performance
),
latest_verdict AS (
  SELECT idea_id, content,
         ROW_NUMBER() OVER (PARTITION BY idea_id ORDER BY id DESC) AS rn
  FROM llm_verdicts WHERE kind = 'verdict'
)
"""
_IDEA_SELECT = """
SELECT i.id, i.issue_id, i.kind, i.ticker, i.company, i.direction, i.thesis,
       i.challenge, i.author, i.price_at_pitch, i.pitch_date, i.target_price,
       isu.season, isu.issue_number,
       lp.current_price, lp.return_pct,
       lv.content AS verdict_content
"""
_IDEA_FROM = """
FROM ideas i
JOIN issues isu ON isu.id = i.issue_id
LEFT JOIN latest_perf lp ON lp.idea_id = i.id AND lp.rn = 1
LEFT JOIN latest_verdict lv ON lv.idea_id = i.id AND lv.rn = 1
"""


def _idea_row_to_dict(row) -> dict:
    item = dict(row)
    item["season"] = item.get("season") or ""
    try:
        verdict = json.loads(item.pop("verdict_content", None) or "{}")
    except json.JSONDecodeError:
        verdict = {}
    item["verdict"] = verdict.get("verdict")
    item["verdict_explanation"] = verdict.get("explanation")
    return item


async def _idea_rows(
    conn,
    where_sql: str = "",
    params: tuple = (),
    order_by: str = "COALESCE(isu.issue_number,0) DESC, i.id DESC",
    limit: int | None = None,
    offset: int = 0,
) -> list[dict]:
    sql = _IDEA_CTE + _IDEA_SELECT + _IDEA_FROM
    if where_sql:
        sql += " WHERE " + where_sql
    sql += f" ORDER BY {order_by}"
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params = tuple(params) + (limit, offset)
    rows = await conn.execute_fetchall(sql, params)
    return [_idea_row_to_dict(r) for r in rows]


async def _idea_count(conn, where_sql: str = "", params: tuple = ()) -> int:
    sql = _IDEA_CTE + "SELECT COUNT(*) AS n" + _IDEA_FROM
    if where_sql:
        sql += " WHERE " + where_sql
    row = await conn.execute_fetchall(sql, params)
    return row[0]["n"] if row else 0


async def _fetch_json(conn, query: str, params=()):
    rows = await conn.execute_fetchall(query, params)
    return [dict(r) for r in rows]


async def _latest_picks(conn):
    """Best-idea picks from the most recent analyzed issue."""
    rows = await conn.execute_fetchall(
        "SELECT i.id AS issue_id, i.season, i.title, i.issue_number "
        "FROM issues i WHERE i.status = 'analyzed' "
        "ORDER BY COALESCE(i.issue_number,0) DESC LIMIT 1"
    )
    if not rows:
        return None
    issue = dict(rows[0])
    picks_rows = await conn.execute_fetchall(
        """SELECT lv.content, i.id AS idea_id, i.ticker, i.company, i.kind, i.direction
           FROM llm_verdicts lv
           JOIN ideas i ON i.id = lv.idea_id
           WHERE lv.kind = 'best_pick' AND i.issue_id = ?
           ORDER BY lv.id DESC LIMIT 20""",
        (issue["issue_id"],),
    )
    picks = []
    for row in picks_rows:
        try:
            content = json.loads(row["content"])
        except json.JSONDecodeError:
            continue
        picks.append({"idea_id": row["idea_id"], "ticker": row["ticker"], "company": row["company"], **content})
    picks.sort(key=lambda p: p.get("score", 0), reverse=True)
    issue["picks"] = picks
    return issue


async def _highlights(conn, limit: int = 12):
    """Recent ideas with their verdict + return, for the highlights strip."""
    return await _idea_rows(conn, where_sql="i.ticker IS NOT NULL", limit=limit)


@router.get("/")
async def index(request: Request, db=Depends(get_db)):
    issues = await _fetch_json(
        db,
        "SELECT id, title, season, issue_number, status, source_url FROM issues ORDER BY COALESCE(issue_number,0) DESC",
    )
    highlights = await _highlights(db)
    latest = await _latest_picks(db)
    ctx = {
        "request": request,
        "issues": issues,
        "highlights": highlights,
        "latest_picks": latest,
    }
    return templates.TemplateResponse(request, "index.html", ctx)


@router.get("/ideas")
async def ideas_search(
    request: Request,
    q: str = "",
    kind: str = "",
    direction: str = "",
    verdict: str = "",
    page: int = 1,
    db=Depends(get_db),
):
    clauses = ["i.ticker IS NOT NULL"]
    params: list = []
    if q:
        clauses.append("(i.ticker LIKE ? OR i.company LIKE ?)")
        like = f"%{q}%"
        params += [like, like]
    if kind in ("pitch", "position"):
        clauses.append("i.kind = ?")
        params.append(kind)
    if direction in ("long", "short", "long/short"):
        clauses.append("i.direction = ?")
        params.append(direction)
    if verdict in ("worked", "partial", "failed", "inconclusive"):
        clauses.append("json_extract(lv.content, '$.verdict') = ?")
        params.append(verdict)
    where_sql = " AND ".join(clauses)

    page = max(page, 1)
    total = await _idea_count(db, where_sql, tuple(params))
    ideas = await _idea_rows(
        db, where_sql, tuple(params), limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE
    )
    ctx = {
        "request": request,
        "ideas": ideas,
        "q": q,
        "kind": kind,
        "direction": direction,
        "verdict": verdict,
        "page": page,
        "total": total,
        "page_size": PAGE_SIZE,
        "has_next": page * PAGE_SIZE < total,
        "has_prev": page > 1,
    }
    return templates.TemplateResponse(request, "ideas.html", ctx)


@router.get("/issues/{issue_id}")
async def issue_detail(issue_id: int, request: Request, db=Depends(get_db)):
    row = await db.execute_fetchall("SELECT * FROM issues WHERE id = ?", (issue_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Issue not found")
    issue = dict(row[0])
    ideas = await _idea_rows(
        db, where_sql="i.issue_id = ?", params=(issue_id,), order_by="i.id ASC"
    )

    prev_row = await db.execute_fetchall(
        "SELECT id, title FROM issues WHERE COALESCE(issue_number,0) < COALESCE(?,0) "
        "ORDER BY COALESCE(issue_number,0) DESC LIMIT 1",
        (issue["issue_number"],),
    )
    next_row = await db.execute_fetchall(
        "SELECT id, title FROM issues WHERE COALESCE(issue_number,0) > COALESCE(?,0) "
        "ORDER BY COALESCE(issue_number,0) ASC LIMIT 1",
        (issue["issue_number"],),
    )
    issue["prev_issue"] = dict(prev_row[0]) if prev_row else None
    issue["next_issue"] = dict(next_row[0]) if next_row else None

    return templates.TemplateResponse(request, "issue.html", {"issue": issue, "ideas": ideas})


@router.get("/ideas/{idea_id}")
async def idea_detail(idea_id: int, request: Request, db=Depends(get_db)):
    row = await db.execute_fetchall(
        """SELECT i.*, isu.season, isu.title AS issue_title, isu.id AS issue_id
           FROM ideas i JOIN issues isu ON isu.id = i.issue_id WHERE i.id = ?""",
        (idea_id,),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Idea not found")
    idea = dict(row[0])

    perf = await _fetch_json(
        db,
        "SELECT * FROM performance WHERE idea_id = ? ORDER BY id DESC LIMIT 1",
        (idea_id,),
    )
    idea["performance"] = perf[0] if perf else None

    # Re-running analysis inserts a new verdict row rather than replacing the
    # old one (so history isn't lost), so only the latest row per kind should
    # be shown here — otherwise a corrected verdict displays stacked on top
    # of the stale one it superseded.
    verdicts = await _fetch_json(
        db,
        """SELECT kind, content FROM llm_verdicts lv
           WHERE idea_id = ? AND id = (
             SELECT MAX(id) FROM llm_verdicts WHERE idea_id = lv.idea_id AND kind = lv.kind
           )
           ORDER BY id""",
        (idea_id,),
    )
    idea["verdicts"] = []
    for v in verdicts:
        try:
            idea["verdicts"].append({"kind": v["kind"], **json.loads(v["content"])})
        except json.JSONDecodeError:
            idea["verdicts"].append({"kind": v["kind"]})

    ticker = idea.get("ticker")
    if ticker:
        idea["price_cache"] = await prices.current_price(
            prices.format_ticker(ticker), company=idea.get("company")
        )

    prev_row = await db.execute_fetchall(
        "SELECT id, ticker, company FROM ideas WHERE issue_id = ? AND id < ? ORDER BY id DESC LIMIT 1",
        (idea["issue_id"], idea_id),
    )
    next_row = await db.execute_fetchall(
        "SELECT id, ticker, company FROM ideas WHERE issue_id = ? AND id > ? ORDER BY id ASC LIMIT 1",
        (idea["issue_id"], idea_id),
    )
    idea["prev_idea"] = dict(prev_row[0]) if prev_row else None
    idea["next_idea"] = dict(next_row[0]) if next_row else None

    return templates.TemplateResponse(request, "idea.html", {"idea": idea})
