import asyncio
import os
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.db import connect, init_db

TEST_DB = Path("/tmp/opencode/value-investing-test.db")
TEST_ADMIN_PASSWORD = "test-admin-password"


@pytest.fixture(autouse=True)
def _reset_price_cache():
    """prices.py keeps in-process caches; tests must not leak across them."""
    from app.services import prices

    prices._price_cache.clear()
    prices._symbol_cache.clear()
    prices._fx_cache.clear()
    yield
    prices._price_cache.clear()
    prices._symbol_cache.clear()
    prices._fx_cache.clear()


@pytest.fixture
def fake_httpx(monkeypatch):
    """Install a canned-response handler for every httpx.AsyncClient built during
    the test, via httpx's own MockTransport (no extra dependency needed).

    Usage: fake_httpx(lambda request: httpx.Response(200, json={...}))
    """

    def _install(handler):
        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs.pop("transport", None)
            kwargs["transport"] = httpx.MockTransport(handler)
            original_init(self, *args, **kwargs)

        monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    return _install


@pytest_asyncio.fixture
async def db(tmp_path):
    db_path = tmp_path / "test.db"
    await init_db(str(db_path))
    conn = await connect(str(db_path))
    yield conn
    await conn.close()


@pytest_asyncio.fixture
async def anon_client(tmp_path, monkeypatch):
    """A TestClient with no admin session — for exercising what a visitor who
    hasn't logged in can and can't reach."""
    db_path = tmp_path / "app-test.db"
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("ADMIN_PASSWORD", TEST_ADMIN_PASSWORD)
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret")
    from app.db import init_db
    await init_db(str(db_path))

    # Fresh app instance so lifespan initializes the right db
    from app.main import app
    from fastapi.testclient import TestClient
    with TestClient(app) as tc:
        yield tc


@pytest_asyncio.fixture
async def client(anon_client):
    """A TestClient already logged in to /admin (session cookie carries over
    to every subsequent request, same as a real browser)."""
    resp = anon_client.post(
        "/admin/login", data={"password": TEST_ADMIN_PASSWORD}, follow_redirects=False
    )
    assert resp.status_code == 303
    return anon_client
