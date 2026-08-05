import asyncio
import time

from app.db import connect, init_db


async def test_index_200(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Graham" in resp.text


async def test_admin_200(client):
    resp = client.get("/admin")
    assert resp.status_code == 200


async def test_admin_login_page_200(anon_client):
    resp = anon_client.get("/admin/login")
    assert resp.status_code == 200
    assert "Admin login" in resp.text


async def test_admin_redirects_anonymous_to_login(anon_client):
    resp = anon_client.get("/admin", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].endswith("/admin/login")


async def test_admin_rejects_wrong_password(anon_client):
    resp = anon_client.post("/admin/login", data={"password": "wrong-password"})
    assert resp.status_code == 401
    assert "Wrong password" in resp.text


async def test_admin_login_then_page_200(anon_client):
    from tests.conftest import TEST_ADMIN_PASSWORD

    login = anon_client.post(
        "/admin/login", data={"password": TEST_ADMIN_PASSWORD}, follow_redirects=False
    )
    assert login.status_code == 303
    resp = anon_client.get("/admin")
    assert resp.status_code == 200


async def test_admin_logout_clears_session(client):
    assert client.get("/admin").status_code == 200
    client.post("/admin/logout")
    resp = client.get("/admin", follow_redirects=False)
    assert resp.status_code == 303


async def test_admin_ingest_requires_auth(anon_client):
    resp = anon_client.post("/admin/ingest", data={"url": "https://example.com/x.pdf"})
    assert resp.status_code == 401


async def test_admin_backfill_requires_auth(anon_client):
    resp = anon_client.post("/admin/backfill")
    assert resp.status_code == 401


async def test_analyze_and_jobs_latest_are_public(anon_client, tmp_path):
    """Invoked from the public issue page, not the admin page — must not
    require an admin login."""
    db_path = tmp_path / "app-test.db"
    await init_db(str(db_path))
    conn = await connect(str(db_path))
    await conn.execute(
        "INSERT INTO issues (source_url, title, status) VALUES ('http://x/9.pdf', 'T9', 'parsed')"
    )
    await conn.commit()
    issue_id = (await conn.execute_fetchall("SELECT last_insert_rowid() AS id"))[0]["id"]
    await conn.close()

    resp = anon_client.post(f"/admin/issues/{issue_id}/analyze")
    assert resp.status_code == 200

    resp = anon_client.get("/admin/jobs/latest?kind=analyze")
    assert resp.status_code == 200


async def test_issue_detail_404_styled(client):
    resp = client.get("/issues/999")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("text/html")
    assert "Back to dashboard" in resp.text


async def test_admin_404_stays_json(client):
    resp = client.get("/admin/nope-not-a-route")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/json")


async def test_issue_detail_200(client, tmp_path):
    # Seed the app's DB (which lives at tmp_path/app-test.db per the client fixture).
    db_path = tmp_path / "app-test.db"
    await init_db(str(db_path))
    conn = await connect(str(db_path))
    await conn.execute(
        "INSERT INTO issues (source_url, title, status) VALUES ('http://x/1.pdf', 'Test', 'parsed')"
    )
    await conn.commit()
    await conn.close()

    resp = client.get("/issues/1")
    assert resp.status_code == 200


async def test_idea_detail_shows_only_latest_verdict(client, tmp_path):
    """Re-running analysis inserts a new verdict row rather than replacing
    the old one; the page must show only the latest, not both stacked."""
    db_path = tmp_path / "app-test.db"
    await init_db(str(db_path))
    conn = await connect(str(db_path))
    await conn.execute(
        "INSERT INTO issues (source_url, title, status) VALUES ('http://x/4.pdf', 'T4', 'parsed')"
    )
    await conn.commit()
    issue_id = (await conn.execute_fetchall("SELECT last_insert_rowid() AS id"))[0]["id"]
    await conn.execute(
        "INSERT INTO ideas (issue_id, kind, ticker, company, direction, thesis) "
        "VALUES (?, 'pitch', 'ACME', 'Acme Corp', 'long', 'thesis')",
        (issue_id,),
    )
    await conn.commit()
    idea_id = (await conn.execute_fetchall("SELECT last_insert_rowid() AS id"))[0]["id"]
    await conn.execute(
        "INSERT INTO llm_verdicts (idea_id, kind, content) VALUES (?, 'verdict', ?)",
        (idea_id, '{"verdict": "failed", "explanation": "stale premature judgement"}'),
    )
    await conn.execute(
        "INSERT INTO llm_verdicts (idea_id, kind, content) VALUES (?, 'verdict', ?)",
        (idea_id, '{"verdict": "inconclusive", "explanation": "corrected judgement"}'),
    )
    await conn.commit()
    await conn.close()

    resp = client.get(f"/ideas/{idea_id}")
    assert resp.status_code == 200
    assert "corrected judgement" in resp.text
    assert "stale premature judgement" not in resp.text


async def test_admin_ingest_requires_url(client):
    resp = client.post("/admin/ingest")
    assert resp.status_code in (400, 307)


async def test_admin_ingest_invalid_url(client):
    resp = client.post("/admin/ingest", data={"url": "not-a-url"})
    assert resp.status_code == 400


async def test_ideas_search_200(client):
    resp = client.get("/ideas")
    assert resp.status_code == 200
    assert "All ideas" in resp.text


async def test_ideas_search_filters(client, tmp_path):
    db_path = tmp_path / "app-test.db"
    await init_db(str(db_path))
    conn = await connect(str(db_path))
    await conn.execute(
        "INSERT INTO issues (source_url, title, status, issue_number) "
        "VALUES ('http://x/2.pdf', 'Issue 2', 'parsed', 2)"
    )
    await conn.commit()
    issue_id = (await conn.execute_fetchall("SELECT last_insert_rowid() AS id"))[0]["id"]
    await conn.execute(
        "INSERT INTO ideas (issue_id, kind, ticker, company, direction, thesis) "
        "VALUES (?, 'pitch', 'ACME', 'Acme Corp', 'long', 'cheap')",
        (issue_id,),
    )
    await conn.commit()
    await conn.close()

    resp = client.get("/ideas?q=ACME")
    assert resp.status_code == 200
    assert "ACME" in resp.text

    resp = client.get("/ideas?q=NOPEMATCH")
    assert resp.status_code == 200
    assert "No ideas match" in resp.text

    resp = client.get("/ideas?direction=short")
    assert resp.status_code == 200
    assert "No ideas match" in resp.text


async def test_backfill_starts_background_job(client, tmp_path, monkeypatch):
    from app.services import ingest

    async def fake_ingest(url):
        return {"ok": True, "issue_id": 1, "ideas": 0, "error": None}

    monkeypatch.setattr(ingest, "ingest_issue", fake_ingest)

    db_path = tmp_path / "app-test.db"
    await init_db(str(db_path))

    resp = client.post("/admin/backfill")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "job_id" in data

    job = {"status": "running"}
    for _ in range(60):
        job = client.get("/admin/jobs/latest?kind=backfill").json()
        if job.get("status") != "running":
            break
        time.sleep(0.05)
    assert job["status"] == "done"


async def test_backfill_rejects_when_already_running(client, tmp_path, monkeypatch):
    from app.services import ingest

    async def slow_ingest(url):
        await asyncio.sleep(1)
        return {"ok": True, "issue_id": 1, "ideas": 0, "error": None}

    monkeypatch.setattr(ingest, "ingest_issue", slow_ingest)
    db_path = tmp_path / "app-test.db"
    await init_db(str(db_path))

    first = client.post("/admin/backfill")
    assert first.json()["ok"] is True

    second = client.post("/admin/backfill")
    assert second.json()["ok"] is False


async def test_analyze_issue_starts_background_job(client, tmp_path, monkeypatch):
    from app.services import analyst

    db_path = tmp_path / "app-test.db"
    await init_db(str(db_path))
    conn = await connect(str(db_path))
    await conn.execute(
        "INSERT INTO issues (source_url, title, status) VALUES ('http://x/3.pdf', 'T3', 'parsed')"
    )
    await conn.commit()
    issue_id = (await conn.execute_fetchall("SELECT last_insert_rowid() AS id"))[0]["id"]
    await conn.close()

    async def fake_analyze_issue(iid, db_path=None):
        return {"issue_id": iid, "results": []}

    monkeypatch.setattr(analyst, "analyze_issue", fake_analyze_issue)

    resp = client.post(f"/admin/issues/{issue_id}/analyze")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    job = {"status": "running"}
    for _ in range(60):
        job = client.get("/admin/jobs/latest?kind=analyze").json()
        if job.get("status") != "running":
            break
        time.sleep(0.05)
    assert job["status"] == "done"
