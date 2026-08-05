import json

import pytest

from app.db import connect, init_db
from app.services import analyst


async def _seed_issue_and_idea(db_path, direction="long", price_at_pitch=100.0):
    await init_db(db_path)
    conn = await connect(db_path)
    try:
        await conn.execute(
            "INSERT INTO issues (source_url, title, status) VALUES ('http://x/1.pdf', 'Test', 'parsed')"
        )
        await conn.commit()
        issue_id = (await conn.execute_fetchall("SELECT last_insert_rowid() AS id"))[0]["id"]
        await conn.execute(
            """INSERT INTO ideas (issue_id, kind, ticker, company, direction, thesis, price_at_pitch)
               VALUES (?, 'pitch', 'ACME', 'Acme Corp', ?, 'cheap stock', ?)""",
            (issue_id, direction, price_at_pitch),
        )
        await conn.commit()
        idea_id = (await conn.execute_fetchall("SELECT last_insert_rowid() AS id"))[0]["id"]
    finally:
        await conn.close()
    return issue_id, idea_id


async def test_refresh_idea_performance(tmp_path, monkeypatch):
    db_path = str(tmp_path / "a.db")
    _, idea_id = await _seed_issue_and_idea(db_path, price_at_pitch=100.0)

    async def fake_current_price(ticker, company=None):
        return 150.0, "2026-01-01"

    monkeypatch.setattr(analyst.prices, "current_price", fake_current_price)

    result = await analyst.refresh_idea_performance(idea_id, db_path=db_path)
    assert result["ok"] is True
    assert result["return_pct"] == pytest.approx(50.0)


async def test_refresh_idea_performance_short_inverts_return(tmp_path, monkeypatch):
    db_path = str(tmp_path / "a.db")
    _, idea_id = await _seed_issue_and_idea(db_path, direction="short", price_at_pitch=100.0)

    async def fake_current_price(ticker, company=None):
        return 150.0, "2026-01-01"

    monkeypatch.setattr(analyst.prices, "current_price", fake_current_price)

    result = await analyst.refresh_idea_performance(idea_id, db_path=db_path)
    assert result["return_pct"] == pytest.approx(-50.0)


async def test_refresh_idea_performance_no_price_data(tmp_path, monkeypatch):
    db_path = str(tmp_path / "a.db")
    _, idea_id = await _seed_issue_and_idea(db_path)

    async def fake_current_price(ticker, company=None):
        return None, None

    monkeypatch.setattr(analyst.prices, "current_price", fake_current_price)

    result = await analyst.refresh_idea_performance(idea_id, db_path=db_path)
    assert result["ok"] is False


async def test_judge_idea_verdict(tmp_path, monkeypatch):
    db_path = str(tmp_path / "a.db")
    _, idea_id = await _seed_issue_and_idea(db_path)

    async def fake_judge_idea(thesis, direction, return_pct, months_elapsed=None):
        return {"verdict": "worked", "explanation": "up big", "confidence": "high"}

    monkeypatch.setattr(analyst.llm, "judge_idea", fake_judge_idea)

    result = await analyst.judge_idea_verdict(idea_id, db_path=db_path)
    assert result["verdict"] == "worked"

    conn = await connect(db_path)
    try:
        rows = await conn.execute_fetchall("SELECT content FROM llm_verdicts WHERE idea_id = ?", (idea_id,))
    finally:
        await conn.close()
    assert len(rows) == 1
    assert json.loads(rows[0]["content"])["verdict"] == "worked"


def test_months_since_pitch():
    from datetime import date, timedelta
    from app.services.analyst import months_since_pitch

    assert months_since_pitch(None) is None
    assert months_since_pitch("garbage") is None

    recent = (date.today() - timedelta(days=120)).isoformat()
    assert months_since_pitch(recent) == pytest.approx(120 / 30.44, abs=0.1)


async def test_judge_idea_verdict_passes_elapsed_months(tmp_path, monkeypatch):
    """A pitch dated a few months ago must not be judged the same as one
    with no elapsed-time context — see llm.judge_idea's verdict rules."""
    db_path = str(tmp_path / "a.db")
    await init_db(db_path)
    conn = await connect(db_path)
    try:
        await conn.execute(
            "INSERT INTO issues (source_url, title, status) VALUES ('http://x/2.pdf', 'Test', 'parsed')"
        )
        await conn.commit()
        issue_id = (await conn.execute_fetchall("SELECT last_insert_rowid() AS id"))[0]["id"]
        await conn.execute(
            """INSERT INTO ideas (issue_id, kind, ticker, company, direction, thesis, pitch_date)
               VALUES (?, 'pitch', 'ACME', 'Acme Corp', 'long', '3-year target thesis', '2026-04')""",
            (issue_id,),
        )
        await conn.commit()
        idea_id = (await conn.execute_fetchall("SELECT last_insert_rowid() AS id"))[0]["id"]
    finally:
        await conn.close()

    captured = {}

    async def fake_judge_idea(thesis, direction, return_pct, months_elapsed=None):
        captured["months_elapsed"] = months_elapsed
        return {"verdict": "inconclusive", "explanation": "too early", "confidence": "low"}

    monkeypatch.setattr(analyst.llm, "judge_idea", fake_judge_idea)
    await analyst.judge_idea_verdict(idea_id, db_path=db_path)
    assert captured["months_elapsed"] is not None
    assert captured["months_elapsed"] < 12


async def test_judge_idea_verdict_llm_failure_returns_error(tmp_path, monkeypatch):
    db_path = str(tmp_path / "a.db")
    _, idea_id = await _seed_issue_and_idea(db_path)

    async def fake_judge_idea(thesis, direction, return_pct, months_elapsed=None):
        return None

    monkeypatch.setattr(analyst.llm, "judge_idea", fake_judge_idea)

    result = await analyst.judge_idea_verdict(idea_id, db_path=db_path)
    assert result["ok"] is False

    conn = await connect(db_path)
    try:
        rows = await conn.execute_fetchall("SELECT content FROM llm_verdicts WHERE idea_id = ?", (idea_id,))
    finally:
        await conn.close()
    assert len(rows) == 0


async def test_analyze_issue_marks_analyzed(tmp_path, monkeypatch):
    db_path = str(tmp_path / "a.db")
    issue_id, _ = await _seed_issue_and_idea(db_path)

    async def fake_current_price(ticker, company=None):
        return 120.0, "2026-01-01"

    async def fake_judge_idea(thesis, direction, return_pct, months_elapsed=None):
        return {"verdict": "partial", "explanation": "meh", "confidence": "medium"}

    monkeypatch.setattr(analyst.prices, "current_price", fake_current_price)
    monkeypatch.setattr(analyst.llm, "judge_idea", fake_judge_idea)

    result = await analyst.analyze_issue(issue_id, db_path=db_path)
    assert len(result["results"]) == 1

    conn = await connect(db_path)
    try:
        row = (await conn.execute_fetchall("SELECT status FROM issues WHERE id = ?", (issue_id,)))[0]
    finally:
        await conn.close()
    assert row["status"] == "analyzed"
