"""Price data via Yahoo Finance chart API (stooq is blocked from this server).

Provides:
- current_price(ticker): latest close
- price_at(ticker, date): closing price on/just after a given date
"""

import logging
import time
from datetime import date, datetime, timedelta, timezone

import httpx

from app.config import get_settings
from app.services.http_utils import with_retry

logger = logging.getLogger(__name__)

_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"

# In-process TTL cache for current_price(): the app runs a single gunicorn
# worker, so this avoids hitting Yahoo on every /ideas/{id} page view.
_CACHE_TTL = 600  # seconds
_price_cache: dict[str, tuple[float | None, str | None, float]] = {}


def _headers() -> dict:
    return {"User-Agent": get_settings().user_agent}


def _parse_result(data: dict) -> tuple[list[int] | None, list[float] | None]:
    try:
        result = data["chart"]["result"][0]
        timestamps = result.get("timestamp")
        closes = result["indicators"]["quote"][0].get("close")
        return timestamps, closes
    except (KeyError, IndexError, TypeError):
        return None, None


async def _fetch(ticker: str, period1: int, period2: int, interval: str = "1d") -> tuple[list[int] | None, list[float] | None]:
    async def _do_request():
        async with httpx.AsyncClient(timeout=30, headers=_headers()) as client:
            resp = await client.get(
                _CHART.format(ticker=ticker),
                params={"period1": period1, "period2": period2, "interval": interval},
            )
            resp.raise_for_status()
            return resp

    try:
        resp = await with_retry(_do_request)
    except httpx.HTTPStatusError as exc:
        logger.warning("Yahoo chart failed for %s: %s", ticker, exc.response.status_code)
        return None, None
    except httpx.TransportError as exc:
        logger.warning("Yahoo chart request failed for %s: %s", ticker, exc)
        return None, None
    return _parse_result(resp.json())


async def current_price(ticker: str) -> tuple[float | None, str | None]:
    """Returns (price, as_of iso date), cached for _CACHE_TTL seconds per ticker."""
    cached = _price_cache.get(ticker)
    if cached is not None and time.monotonic() - cached[2] < _CACHE_TTL:
        return cached[0], cached[1]

    now = int(datetime.now(timezone.utc).timestamp())
    ts, closes = await _fetch(ticker, now - 90 * 86400, now)
    price, as_of = None, None
    if ts and closes:
        for i in range(len(closes) - 1, -1, -1):
            if closes[i] is not None:
                as_of = datetime.fromtimestamp(ts[i], tz=timezone.utc).date().isoformat()
                price = float(closes[i])
                break
    _price_cache[ticker] = (price, as_of, time.monotonic())
    return price, as_of


async def price_at(ticker: str, when: str | date) -> float | None:
    """Closing price on the given date (first trading day on/after it)."""
    if isinstance(when, str):
        d = date.fromisoformat(when)
    else:
        d = when
    period1 = int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())
    period2 = period1 + 400 * 86400
    ts, closes = await _fetch(ticker, period1, period2)
    if not ts or not closes:
        return None
    for i in range(len(closes)):
        if closes[i] is not None:
            return float(closes[i])
    return None


async def price_series(ticker: str, start: date, end: date) -> list[dict]:
    """Daily closes between start and end, for charting."""
    period1 = int(datetime(start.year, start.month, start.day, tzinfo=timezone.utc).timestamp())
    period2 = int(datetime(end.year, end.month, end.day, tzinfo=timezone.utc).timestamp()) + 86400
    ts, closes = await _fetch(ticker, period1, period2, interval="1d")
    if not ts or not closes:
        return []
    return [
        {"date": datetime.fromtimestamp(t, tz=timezone.utc).date().isoformat(), "close": c}
        for t, c in zip(ts, closes)
        if c is not None
    ]


def format_ticker(ticker: str) -> str:
    t = ticker.strip().upper().replace(" ", "")
    if t.endswith(".US") or "." in t:
        t = t.split(".")[0]
    return t
