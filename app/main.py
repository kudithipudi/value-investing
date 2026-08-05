import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.config import get_settings
from app.db import init_db
from app.routers import admin, dashboard

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    logger.info("Startup complete")
    yield


settings = get_settings()
# NOTE: don't pass root_path to FastAPI. nginx strips the /value-investing prefix
# before forwarding, so the app sees bare paths like /static/css/app.css. Setting
# FastAPI root_path makes Starlette's Mount routing expect the prefix to still be
# present, and the /static mount 404s. Templates still get the public prefix via
# the ROOT_PATH env -> {{ prefix }} global.
app = FastAPI(lifespan=lifespan)
_here = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=str(_here / "static")), name="static")
# Signs the admin login cookie. Falls back to admin_password so a fresh
# checkout still runs, but a real deploy should set SESSION_SECRET in .env —
# without a stable secret, every gunicorn restart would log everyone out.
#
# Deliberately left at the default cookie path "/" rather than root_path:
# nginx strips /value-investing before proxying, so the app (and tests, which
# talk to it directly) only ever sees bare paths like "/admin" — a cookie
# scoped to "/value-investing" would never match those and the session would
# silently never be sent back.
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret or settings.admin_password or "dev-only-insecure-secret",
    session_cookie="value_investing_session",
    max_age=12 * 60 * 60,
)
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["prefix"] = settings.root_path

app.include_router(dashboard.router)
app.include_router(admin.router)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    # /admin is an internal/API surface (existing tests expect raw JSON there);
    # reader-facing dashboard routes get a styled error page instead of a bare
    # {"detail": ...} blob.
    if request.url.path.startswith("/admin"):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    return templates.TemplateResponse(
        request,
        "error.html",
        {"status_code": exc.status_code, "detail": exc.detail},
        status_code=exc.status_code,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
