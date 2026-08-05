import asyncio
import json
import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.db import connect, get_db
from app.services import analyst, discovery, ingest, jobs
from app.services.catalog import KNOWN_ISSUES

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["prefix"] = get_settings().root_path

_basic_auth = HTTPBasic()


def require_admin(credentials: HTTPBasicCredentials = Depends(_basic_auth)) -> bool:
    """Guards the management surface (ingest/backfill/score-latest/discover and
    the /admin page itself). Username is ignored, only the password matters.

    /admin/issues/{id}/analyze and /admin/jobs/latest stay unauthenticated —
    they're invoked from public issue/dashboard pages, not the admin page.
    """
    configured = get_settings().admin_password
    if not configured or not secrets.compare_digest(credentials.password, configured):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
            headers={"WWW-Authenticate": 'Basic realm="Admin"'},
        )
    return True


@router.get("", dependencies=[Depends(require_admin)])
async def admin_page(request: Request, db=Depends(get_db)):
    ingested = {
        r["source_url"]
        for r in await db.execute_fetchall("SELECT source_url FROM issues")
    }
    known = [
        {"season": season, "issue_number": num, "title": title, "url": url,
         "ingested": url in ingested}
        for season, num, title, url in KNOWN_ISSUES
    ]
    latest = await db.execute_fetchall(
        "SELECT id, title FROM issues ORDER BY COALESCE(issue_number,0) DESC LIMIT 1"
    )
    return templates.TemplateResponse(
        request,
        "admin.html",
        {"known": known, "latest_issue": dict(latest[0]) if latest else None},
    )


@router.get("/jobs/latest")
async def latest_job(kind: str):
    job = await jobs.get_latest_job(kind)
    return job or {"status": "none"}


@router.post("/ingest", dependencies=[Depends(require_admin)])
async def ingest_issue(request: Request, db=Depends(get_db)):
    form = await request.form()
    url = (form.get("url") or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL required")
    if not discovery.normalize_url(url):
        raise HTTPException(status_code=400, detail="Invalid URL")
    result = await ingest.ingest_issue(url)
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("error", "ingest failed"))
    # nginx strips the /value-investing prefix on the way in and has no
    # proxy_redirect configured, so a bare "/issues/x" Location header would
    # resolve against the domain root in the browser, not this app's sub-path.
    return RedirectResponse(f"{get_settings().root_path}/issues/{result['issue_id']}", status_code=303)


@router.post("/backfill", dependencies=[Depends(require_admin)])
async def backfill():
    if await jobs.is_job_running("backfill"):
        return {"ok": False, "error": "a backfill is already running"}

    conn = await connect()
    try:
        ingested = {
            r["source_url"]
            for r in await conn.execute_fetchall("SELECT source_url FROM issues")
        }
    finally:
        await conn.close()
    to_ingest = [url for url in (entry[3] for entry in KNOWN_ISSUES) if url not in ingested]

    job_id = await jobs.create_job("backfill", note={"done": 0, "total": len(to_ingest)})
    asyncio.create_task(_run_backfill(job_id, to_ingest))
    return {"ok": True, "job_id": job_id, "total": len(to_ingest)}


async def _run_backfill(job_id: int, urls: list[str]) -> None:
    progress = {"done": 0, "total": len(urls), "failed": 0}

    async def _one(url: str):
        result = await ingest.ingest_issue(url)
        progress["done"] += 1
        if not result.get("ok"):
            progress["failed"] += 1
        await jobs.update_job(job_id, note={**progress, "current": url})
        return result

    try:
        await ingest.run_concurrently([_one(u) for u in urls])
        await jobs.update_job(job_id, status="done", note=progress)
    except Exception as exc:  # noqa: BLE001 - job must record failure, not crash silently
        logger.exception("Backfill job %d failed", job_id)
        await jobs.update_job(job_id, status="failed", note={**progress, "error": str(exc)})


@router.post("/issues/{issue_id}/analyze")
async def analyze_issue(issue_id: int):
    if await jobs.is_job_running("analyze"):
        return {"ok": False, "error": "an analysis is already running"}

    job_id = await jobs.create_job("analyze", note={"issue_id": issue_id})
    asyncio.create_task(_run_analyze(job_id, issue_id))
    return {"ok": True, "job_id": job_id}


async def _run_analyze(job_id: int, issue_id: int) -> None:
    try:
        result = await analyst.analyze_issue(issue_id)
        results = result.get("results", [])
        ok = sum(1 for r in results if isinstance(r.get("verdict"), dict) and "verdict" in r["verdict"])
        note = {"issue_id": issue_id, "total": len(results), "ok": ok, "failed": len(results) - ok}
        await jobs.update_job(job_id, status="done", note=note)
    except Exception as exc:  # noqa: BLE001 - job must record failure, not crash silently
        logger.exception("Analyze job %d failed for issue %d", job_id, issue_id)
        await jobs.update_job(job_id, status="failed", note={"issue_id": issue_id, "error": str(exc)})


@router.post("/score-latest", dependencies=[Depends(require_admin)])
async def score_latest():
    """Run best-pick scoring for the most recent issue and persist picks."""
    conn = await connect()
    try:
        latest = await conn.execute_fetchall(
            "SELECT id FROM issues ORDER BY COALESCE(issue_number,0) DESC LIMIT 1"
        )
        if not latest:
            raise HTTPException(status_code=404, detail="No issues ingested")
        issue_id = latest[0]["id"]
        ideas = await conn.execute_fetchall(
            "SELECT id, ticker, company, direction, thesis, challenge, author "
            "FROM ideas WHERE issue_id = ?",
            (issue_id,),
        )
    finally:
        await conn.close()

    payload = [dict(r) for r in ideas]
    picks = await analyst.score_latest_picks_ideas(payload)

    conn = await connect()
    try:
        await conn.execute(
            """DELETE FROM llm_verdicts WHERE kind = 'best_pick' AND idea_id IN
               (SELECT id FROM ideas WHERE issue_id = ?)""",
            (issue_id,),
        )
        for p in picks:
            idea = await conn.execute_fetchall(
                "SELECT id FROM ideas WHERE issue_id = ? AND ticker = ? LIMIT 1",
                (issue_id, p.get("ticker")),
            )
            if not idea:
                continue
            await conn.execute(
                "INSERT INTO llm_verdicts (idea_id, kind, model, content) VALUES (?, 'best_pick', ?, ?)",
                (idea[0]["id"], get_settings().llm_model, json.dumps(p)),
            )
        await conn.commit()
    finally:
        await conn.close()
    return {"ok": True, "picks": len(picks), "issue_id": issue_id}


@router.get("/discover", dependencies=[Depends(require_admin)])
async def discover():
    candidates = await discovery.scan_mirror_archive()
    return {"candidates": candidates}
