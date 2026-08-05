import pytest

from app.db import connect, init_db
from app.services import ingest, statuses


async def _fake_download(url, pdf_dir=None):
    return "fake.pdf"


async def _fake_extract_ideas(text):
    return [{"ticker": "ACME", "company": "Acme Corp", "kind": "pitch", "direction": "long", "thesis": "cheap"}]


def _patch_extraction_pipeline(monkeypatch, extract_ideas_fn):
    monkeypatch.setattr(ingest.downloader, "download_pdf", _fake_download)
    monkeypatch.setattr(ingest.extractor, "extract_pdf_text", lambda p: "some pitch text " * 50)
    monkeypatch.setattr(ingest.extractor, "split_sections", lambda text: [{"is_pitch": True, "text": text}])
    monkeypatch.setattr(ingest.extractor, "has_idea_signal", lambda text: True)
    monkeypatch.setattr(ingest.llm, "extract_ideas", extract_ideas_fn)


async def test_ingest_issue_happy_path(tmp_path, monkeypatch):
    db_path = str(tmp_path / "ingest.db")
    await init_db(db_path)
    _patch_extraction_pipeline(monkeypatch, _fake_extract_ideas)

    result = await ingest.ingest_issue("http://example.com/issue.pdf", db_path=db_path)
    assert result["ok"] is True
    assert result["ideas"] == 1

    conn = await connect(db_path)
    try:
        row = (await conn.execute_fetchall(
            "SELECT status FROM issues WHERE id = ?", (result["issue_id"],)
        ))[0]
        idea_rows = await conn.execute_fetchall(
            "SELECT ticker FROM ideas WHERE issue_id = ?", (result["issue_id"],)
        )
    finally:
        await conn.close()
    assert row["status"] == statuses.PARSED
    assert [r["ticker"] for r in idea_rows] == ["ACME"]


async def test_ingest_issue_already_done_is_rejected(tmp_path, monkeypatch):
    db_path = str(tmp_path / "ingest.db")
    await init_db(db_path)
    _patch_extraction_pipeline(monkeypatch, _fake_extract_ideas)
    url = "http://example.com/issue.pdf"

    first = await ingest.ingest_issue(url, db_path=db_path)
    assert first["ok"] is True

    second = await ingest.ingest_issue(url, db_path=db_path)
    assert second["ok"] is False
    assert "already ingested" in second["error"]


async def test_ingest_issue_retries_cleanly_after_crash(tmp_path, monkeypatch):
    """A crash before the final atomic commit must leave the row retryable,
    not stuck reporting 'already ingested' (see app/services/ingest.py)."""
    db_path = str(tmp_path / "ingest.db")
    await init_db(db_path)
    url = "http://example.com/issue.pdf"

    async def _boom(text):
        raise RuntimeError("simulated crash mid-extraction")

    _patch_extraction_pipeline(monkeypatch, _boom)
    with pytest.raises(RuntimeError):
        await ingest.ingest_issue(url, db_path=db_path)

    conn = await connect(db_path)
    try:
        row = (await conn.execute_fetchall(
            "SELECT status FROM issues WHERE source_url = ?", (url,)
        ))[0]
    finally:
        await conn.close()
    assert row["status"] == statuses.DOWNLOADING

    monkeypatch.setattr(ingest.llm, "extract_ideas", _fake_extract_ideas)
    result = await ingest.ingest_issue(url, db_path=db_path)
    assert result["ok"] is True


async def _fake_download_fail(url, pdf_dir=None):
    return None


async def test_ingest_issue_download_failure(tmp_path, monkeypatch):
    db_path = str(tmp_path / "ingest.db")
    await init_db(db_path)
    monkeypatch.setattr(ingest.downloader, "download_pdf", _fake_download_fail)

    result = await ingest.ingest_issue("http://example.com/issue.pdf", db_path=db_path)
    assert result["ok"] is False
    assert result["error"] == "download failed"

    conn = await connect(db_path)
    try:
        row = (await conn.execute_fetchall(
            "SELECT status FROM issues WHERE id = ?", (result["issue_id"],)
        ))[0]
    finally:
        await conn.close()
    assert row["status"] == statuses.DOWNLOAD_FAILED


async def test_run_concurrently_isolates_failures():
    async def ok():
        return {"ok": True}

    async def boom():
        raise RuntimeError("nope")

    results = await ingest.run_concurrently([ok(), boom(), ok()], concurrency=2)
    assert results[0] == {"ok": True}
    assert results[1]["ok"] is False
    assert results[2] == {"ok": True}
