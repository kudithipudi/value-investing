"""Price data via Yahoo Finance (stooq is blocked from this server).

Yahoo covers most non-US exchanges natively via a dotted suffix on the symbol
(RIO.L on LSE, 0700.HK on HKEX, 7203.T on Tokyo, ...) — the gap for this app
isn't source coverage, it's that ideas.ticker is just a bare symbol with no
exchange info (the newsletter text rarely states one). So in addition to the
chart API, this module also uses Yahoo's own symbol search to resolve a bare
ticker/company to the correct exchange-qualified symbol when the bare ticker
returns no data, and caches the resolution.

Provides:
- current_price(ticker, company): latest close, resolving via company name
  search if the bare ticker has no data
- price_at(ticker, date, company): closing price on/just after a given date
"""

import logging
import re
import time
from datetime import date, datetime, timedelta, timezone

import httpx

from app.config import get_settings
from app.services.http_utils import with_retry

logger = logging.getLogger(__name__)

_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
_SEARCH = "https://query1.finance.yahoo.com/v1/finance/search"

# In-process TTL cache for current_price(): the app runs a single gunicorn
# worker, so this avoids hitting Yahoo on every /ideas/{id} page view.
_CACHE_TTL = 600  # seconds
_price_cache: dict[str, tuple[float | None, str | None, float]] = {}

# Resolved-symbol cache: company name -> Yahoo symbol (or None if not found).
# Ticker-to-exchange mappings don't change, so this is cached for the life of
# the process rather than on the shorter price TTL.
_symbol_cache: dict[str, str | None] = {}


def _headers() -> dict:
    return {"User-Agent": get_settings().user_agent}


def _parse_result(data: dict) -> tuple[list[int] | None, list[float] | None, str | None]:
    try:
        result = data["chart"]["result"][0]
        timestamps = result.get("timestamp")
        closes = result["indicators"]["quote"][0].get("close")
        meta = result.get("meta") or {}
        name = meta.get("longName") or meta.get("shortName")
        return timestamps, closes, name
    except (KeyError, IndexError, TypeError):
        return None, None, None


async def _fetch(ticker: str, period1: int, period2: int, interval: str = "1d") -> tuple[list[int] | None, list[float] | None, str | None]:
    """Returns (timestamps, closes, instrument name). The name lets callers
    catch a bare ticker that resolves to real chart data for the WRONG
    company (e.g. "AMS" is a real, unrelated NYSE American penny stock, not
    Amadeus IT Group) — a case a plain "did the request succeed" check can't
    catch, since Yahoo happily returns valid-looking data for it."""
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
        return None, None, None
    except httpx.TransportError as exc:
        logger.warning("Yahoo chart request failed for %s: %s", ticker, exc)
        return None, None, None
    return _parse_result(resp.json())


def _names_match(company: str, candidate_name: str | None) -> bool:
    if not candidate_name:
        return False
    company_words = set(re.findall(r"[a-z]+", company.lower()))
    candidate_words = set(re.findall(r"[a-z]+", candidate_name.lower()))
    return bool(company_words & candidate_words)


# German regional exchanges that mirror foreign stocks in EUR with thin
# liquidity, distinct from Xetra/Frankfurt (the real primary venues for
# German equities). Yahoo's search frequently ranks these mirrors above a
# stock's actual primary listing, and a mirror's EUR price isn't comparable
# to the USD price_at_pitch the newsletter states — silently picking one
# would produce a nonsense return calculation, so they're used only if
# nothing else matches.
_MIRROR_EXCHANGES = {"MUN", "STU", "HAM", "DUS", "BER", "HAN"}


async def _search_symbol(company: str) -> str | None:
    """Resolve a company name to a Yahoo symbol via Yahoo's own search API.
    Used as a fallback when a bare ticker has no chart data — likely because
    it trades on a non-US exchange Yahoo needs a suffix for."""
    key = company.strip().lower()
    if key in _symbol_cache:
        return _symbol_cache[key]

    async def _do_request():
        async with httpx.AsyncClient(timeout=15, headers=_headers()) as client:
            resp = await client.get(_SEARCH, params={"q": company, "quotesCount": 10, "newsCount": 0})
            resp.raise_for_status()
            return resp

    resolved: str | None = None
    try:
        resp = await with_retry(_do_request, attempts=2)
        quotes = resp.json().get("quotes", [])
        candidates = [
            q for q in quotes
            if q.get("quoteType") == "EQUITY"
            and _names_match(company, q.get("shortname") or q.get("longname"))
        ]
        preferred = [q for q in candidates if q.get("exchange") not in _MIRROR_EXCHANGES]
        pick = (preferred or candidates)
        if pick:
            resolved = pick[0].get("symbol")
    except (httpx.HTTPStatusError, httpx.TransportError) as exc:
        logger.warning("Yahoo symbol search failed for %r: %s", company, exc)

    _symbol_cache[key] = resolved
    return resolved


async def current_price(ticker: str, company: str | None = None) -> tuple[float | None, str | None]:
    """Returns (price, as_of iso date), cached for _CACHE_TTL seconds per ticker.

    Falls back to resolving `company` to an exchange-qualified symbol (see
    _search_symbol) when the bare ticker has no data, OR when it resolves to
    a real but unrelated company (a same-symbol collision — see _fetch).
    """
    cached = _price_cache.get(ticker)
    if cached is not None and time.monotonic() - cached[2] < _CACHE_TTL:
        return cached[0], cached[1]

    price, as_of, name = await _current_price_uncached(ticker)
    if company and (price is None or not _names_match(company, name)):
        if price is not None:
            logger.warning("Ticker %r resolved to %r, not %r — re-resolving by name", ticker, name, company)
        resolved = await _search_symbol(company)
        if resolved and resolved != ticker:
            resolved_price, resolved_as_of, _ = await _current_price_uncached(resolved)
            if resolved_price is not None:
                price, as_of = resolved_price, resolved_as_of
        # else: search couldn't confirm or deny it (e.g. an informal company
        # name Yahoo's search doesn't index, like "Sallie Mae" for SLM
        # Corporation) — keep whatever `price` already is rather than
        # discarding a number we have no actual evidence is wrong.
    _price_cache[ticker] = (price, as_of, time.monotonic())
    return price, as_of


async def _current_price_uncached(ticker: str) -> tuple[float | None, str | None, str | None]:
    now = int(datetime.now(timezone.utc).timestamp())
    ts, closes, name = await _fetch(ticker, now - 90 * 86400, now)
    if ts and closes:
        for i in range(len(closes) - 1, -1, -1):
            if closes[i] is not None:
                as_of = datetime.fromtimestamp(ts[i], tz=timezone.utc).date().isoformat()
                return float(closes[i]), as_of, name
    return None, None, name


async def price_at(ticker: str, when: str | date, company: str | None = None) -> float | None:
    """Closing price on the given date (first trading day on/after it)."""
    if isinstance(when, str):
        d = date.fromisoformat(when)
    else:
        d = when
    period1 = int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())
    period2 = period1 + 400 * 86400

    price, name = await _price_at_uncached(ticker, period1, period2)
    if company and (price is None or not _names_match(company, name)):
        resolved = await _search_symbol(company)
        if resolved and resolved != ticker:
            resolved_price, _ = await _price_at_uncached(resolved, period1, period2)
            if resolved_price is not None:
                price = resolved_price
        # else: keep the original price — see current_price's comment above.
    return price


async def _price_at_uncached(ticker: str, period1: int, period2: int) -> tuple[float | None, str | None]:
    ts, closes, name = await _fetch(ticker, period1, period2)
    if not ts or not closes:
        return None, name
    for i in range(len(closes)):
        if closes[i] is not None:
            return float(closes[i]), name
    return None, name


async def price_series(ticker: str, start: date, end: date) -> list[dict]:
    """Daily closes between start and end, for charting."""
    period1 = int(datetime(start.year, start.month, start.day, tzinfo=timezone.utc).timestamp())
    period2 = int(datetime(end.year, end.month, end.day, tzinfo=timezone.utc).timestamp()) + 86400
    ts, closes, _ = await _fetch(ticker, period1, period2, interval="1d")
    if not ts or not closes:
        return []
    return [
        {"date": datetime.fromtimestamp(t, tz=timezone.utc).date().isoformat(), "close": c}
        for t, c in zip(ts, closes)
        if c is not None
    ]


def format_ticker(ticker: str) -> str:
    """Normalizes a raw extracted ticker into Yahoo's symbol format.

    A dotted suffix is ambiguous: it's either a US dual-class share (BRK.B,
    BF.B -> Yahoo wants a dash: BRK-B) or a real non-US exchange code (RIO.L,
    0700.HK, 7203.T, ...) that Yahoo needs kept as-is. Since real dual-class
    suffixes are effectively always a single "A"/"B", that's the dividing
    line; anything else after a dot is assumed to be an exchange suffix.
    ".US" (not a real Yahoo suffix, sometimes present in source data to mean
    "the US listing") is dropped entirely.
    """
    t = ticker.strip().upper().replace(" ", "")
    if "." in t:
        base, suffix = t.rsplit(".", 1)
        if suffix == "US":
            return base
        if suffix in ("A", "B") and base:
            return f"{base}-{suffix}"
    return t
