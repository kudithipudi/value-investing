import httpx
import pytest

from app.services import llm, prices
from app.services.extractor import extract_pdf_text, has_idea_signal, split_sections


def test_has_idea_signal_true():
    assert has_idea_signal("We bought the stock trading at 8x earnings with upside.")


def test_has_idea_signal_false():
    assert not has_idea_signal("Thank you for joining us today.")


def test_split_sections_pitch_tagged():
    text = (
        "We are pleased to bring you this issue.\n"
        "STOCK PITCH CHALLENGE\n"
        "Long idea: shares trade at a discount to intrinsic value. "
        "The market misunderstands the credit facility. "
        "Management incentives are aligned. This is a compounder. "
        "We see fifty percent upside to fair value over three years. "
        "The balance sheet is strong and the founder owns a large stake. "
        "A potential catalyst is a dividend hike in the next year. "
        "Competitors are retreating from the core market segment. "
        "We recommend the shares for investors with a long horizon. "
        "The short thesis ignores the optionality in the pipeline. "
        "Overall, we think the risk-reward is attractive here. "
        "In closing, we thank the judges and the other participants "
        "for the opportunity to present our thesis today.\n"
        "Thank you for listening.\n"
    )
    sections = split_sections(text)
    assert sections
    assert any(s["is_pitch"] for s in sections)


def test_extract_pdf_text_sample():
    from io import BytesIO

    from pypdf import PdfWriter
    from pypdf.generic import AnnotationBuilder

    writer = PdfWriter()
    page = writer.add_blank_page(width=72, height=72)
    writer.write("/tmp/opencode/tiny.pdf")
    text = extract_pdf_text("/tmp/opencode/tiny.pdf")
    assert isinstance(text, str)


def test_parse_json_fenced():
    assert llm._parse_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_parse_json_bare():
    assert llm._parse_json('{"a": 2}') == {"a": 2}


def test_format_ticker():
    from app.services.prices import format_ticker
    assert format_ticker("aapl.us") == "AAPL"
    # US dual-class shares use Yahoo's dash notation, not a dot.
    assert format_ticker("BRK.B") == "BRK-B"
    assert format_ticker("bf.b") == "BF-B"
    # Real non-US exchange suffixes must be preserved, not stripped.
    assert format_ticker("rio.l") == "RIO.L"
    assert format_ticker("0700.hk") == "0700.HK"
    assert format_ticker("7203.t") == "7203.T"


def test_normalize_url():
    from app.services.discovery import normalize_url
    assert normalize_url("https://business.columbia.edu/x.pdf") == "https://business.columbia.edu/x.pdf"
    assert normalize_url("www.grahamanddoddsville.net/a.pdf") == "https://www.grahamanddoddsville.net/a.pdf"
    assert normalize_url("business.columbia.edu/x.pdf") == "https://business.columbia.edu/x.pdf"
    assert normalize_url("not-a-url") is None


def test_issue_number_from_url():
    from app.services.discovery import _issue_number_from_url
    # %20 is URL-encoded space; digits inside must not corrupt the issue number.
    url = "https://example.com/Graham%20_%20Doddsville_Issue%2033_v23.pdf"
    assert _issue_number_from_url(url) == 33


def test_parse_pitch_date():
    from datetime import date
    from app.services.analyst import parse_pitch_date
    assert parse_pitch_date("2024-04") == date(2024, 4, 15)
    assert parse_pitch_date("Spring 2016") == date(2016, 5, 15)
    assert parse_pitch_date("Winter 2017") == date(2017, 2, 15)
    assert parse_pitch_date(None) is None
    assert parse_pitch_date("garbage") is None


_CHART_OK = {
    "chart": {"result": [{"timestamp": [1700000000], "indicators": {"quote": [{"close": [123.45]}]}}]}
}


async def test_prices_current_price_retries_then_succeeds(fake_httpx, monkeypatch):
    monkeypatch.setenv("DB_PATH", "unused.db")
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 2:
            return httpx.Response(503)
        return httpx.Response(200, json=_CHART_OK)

    fake_httpx(handler)
    price, as_of, currency = await prices.current_price("AAPL")
    assert price == 123.45
    assert calls["n"] == 2


async def test_prices_current_price_caches(fake_httpx):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(200, json=_CHART_OK)

    fake_httpx(handler)
    await prices.current_price("MSFT")
    await prices.current_price("MSFT")
    assert calls["n"] == 1


async def test_prices_current_price_gives_up_on_404(fake_httpx):
    def handler(request):
        return httpx.Response(404)

    fake_httpx(handler)
    price, as_of, currency = await prices.current_price("NOPE")
    assert price is None


_SEARCH_MATCH = {
    "quotes": [
        {"symbol": "RIO.L", "shortname": "Rio Tinto Group", "quoteType": "EQUITY"},
    ]
}
_SEARCH_NO_MATCH = {"quotes": []}


_EMPTY_CHART = {"chart": {"result": [{"timestamp": [], "indicators": {"quote": [{"close": []}]}}]}}


async def test_prices_current_price_resolves_via_company_search(fake_httpx):
    """A bare ticker with no chart data falls back to a company-name search
    for the correctly exchange-qualified symbol (e.g. a London listing)."""

    def handler(request):
        url = str(request.url)
        if "/finance/search" in url:
            return httpx.Response(200, json=_SEARCH_MATCH)
        if "/chart/RIO.L" in url:
            return httpx.Response(200, json=_CHART_OK)
        return httpx.Response(200, json=_EMPTY_CHART)

    fake_httpx(handler)
    price, as_of, currency = await prices.current_price("RIO", company="Rio Tinto Group")
    assert price == 123.45


async def test_prices_current_price_search_no_match_stays_none(fake_httpx):
    def handler(request):
        if "/finance/search" in str(request.url):
            return httpx.Response(200, json=_SEARCH_NO_MATCH)
        return httpx.Response(200, json=_EMPTY_CHART)

    fake_httpx(handler)
    price, as_of, currency = await prices.current_price("XXXX", company="Some Untraceable Co")
    assert price is None


def test_names_match():
    assert prices._names_match("Amadeus IT Group", "Amadeus IT Group, S.A.")
    assert not prices._names_match("Amadeus IT Group", "American Shared Hospital Services")
    assert not prices._names_match("Amadeus IT Group", None)


_CHART_WRONG_COMPANY = {
    "chart": {"result": [{
        "timestamp": [1700000000],
        "indicators": {"quote": [{"close": [1.49]}]},
        "meta": {"longName": "American Shared Hospital Services"},
    }]}
}
_CHART_CORRECT_COMPANY = {
    "chart": {"result": [{
        "timestamp": [1700000000],
        "indicators": {"quote": [{"close": [57.56]}]},
        "meta": {"longName": "Amadeus IT Group, S.A.", "currency": "EUR"},
    }]}
}
_SEARCH_AMADEUS = {
    "quotes": [{"symbol": "AMS.MC", "shortname": "AMADEUS IT GROUP, S.A.", "exchange": "MCE", "quoteType": "EQUITY"}]
}


async def test_prices_current_price_detects_wrong_company_collision(fake_httpx):
    """A bare ticker that resolves to real chart data for an unrelated
    company (AMS = American Shared Hospital Services, not Amadeus IT Group)
    must not be trusted — re-resolve by company name instead."""

    def handler(request):
        url = str(request.url)
        if "/finance/search" in url:
            return httpx.Response(200, json=_SEARCH_AMADEUS)
        if "/chart/AMS.MC" in url:
            return httpx.Response(200, json=_CHART_CORRECT_COMPANY)
        if "/chart/AMS" in url:
            return httpx.Response(200, json=_CHART_WRONG_COMPANY)
        return httpx.Response(200, json=_EMPTY_CHART)

    fake_httpx(handler)
    price, as_of, currency = await prices.current_price("AMS", company="Amadeus IT Group")
    assert price == 57.56
    assert currency == "EUR"


async def test_prices_current_price_keeps_original_when_search_finds_nothing(fake_httpx):
    """A name mismatch that search *can't* resolve either (e.g. the stored
    company field is an informal name like "Sallie Mae" for SLM Corporation,
    which Yahoo's search doesn't index) must not discard a real price we
    have no actual evidence is wrong — that's strictly worse than keeping it."""

    def handler(request):
        url = str(request.url)
        if "/finance/search" in url:
            return httpx.Response(200, json=_SEARCH_NO_MATCH)
        return httpx.Response(200, json=_CHART_WRONG_COMPANY)  # named "American Shared..."

    fake_httpx(handler)
    price, as_of, currency = await prices.current_price("SLM", company="Sallie Mae")
    assert price == 1.49  # kept, not nulled out, despite the name mismatch


async def test_prices_current_price_without_company_trusts_bare_ticker(fake_httpx):
    """No company to verify against -> unchanged behavior for callers that
    don't pass one."""

    def handler(request):
        return httpx.Response(200, json=_CHART_WRONG_COMPANY)

    fake_httpx(handler)
    price, as_of, currency = await prices.current_price("AMS")
    assert price == 1.49


_FX_EUR_USD = {
    "chart": {"result": [{"timestamp": [1700000000], "indicators": {"quote": [{"close": [1.16]}]}}]}
}


async def test_convert_to_usd(fake_httpx):
    def handler(request):
        return httpx.Response(200, json=_FX_EUR_USD)

    fake_httpx(handler)
    usd = await prices.convert_to_usd(57.56, "EUR")
    assert usd == pytest.approx(57.56 * 1.16)


async def test_convert_to_usd_noop_for_usd():
    # USD needs no FX lookup — must not attempt a network call.
    usd = await prices.convert_to_usd(100.0, "USD")
    assert usd == 100.0


async def test_convert_to_usd_none_amount_or_currency():
    assert await prices.convert_to_usd(None, "EUR") is None
    assert await prices.convert_to_usd(100.0, None) is None


async def test_convert_to_usd_missing_rate_returns_none(fake_httpx):
    def handler(request):
        return httpx.Response(404)

    fake_httpx(handler)
    assert await prices.convert_to_usd(100.0, "ZZZ") is None


async def test_fx_rate_is_cached(fake_httpx):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(200, json=_FX_EUR_USD)

    fake_httpx(handler)
    await prices.convert_to_usd(10.0, "EUR")
    await prices.convert_to_usd(20.0, "EUR")
    assert calls["n"] == 1


_SEARCH_MIRROR_AND_PRIMARY = {
    "quotes": [
        {"symbol": "GEB.MU", "shortname": "Bank of Georgia Group", "exchange": "MUN", "quoteType": "EQUITY"},
        {"symbol": "BDGSF", "shortname": "Bank of Georgia Group", "exchange": "PNK", "quoteType": "EQUITY"},
    ]
}


async def test_search_symbol_deprioritizes_mirror_exchanges(fake_httpx):
    """A thin EUR-priced German mirror listing must lose to a USD-priced
    listing, even if the mirror is ranked first by Yahoo's search — a mirror's
    price isn't comparable to the USD reference price the newsletter states."""

    def handler(request):
        return httpx.Response(200, json=_SEARCH_MIRROR_AND_PRIMARY)

    fake_httpx(handler)
    resolved = await prices._search_symbol("Bank of Georgia Group")
    assert resolved == "BDGSF"


async def test_prices_search_symbol_is_cached(fake_httpx):
    calls = {"search": 0}

    def handler(request):
        url = str(request.url)
        if "/finance/search" in url:
            calls["search"] += 1
            return httpx.Response(200, json=_SEARCH_MATCH)
        if "/chart/RIO.L" in url:
            return httpx.Response(200, json=_CHART_OK)
        return httpx.Response(200, json=_EMPTY_CHART)

    fake_httpx(handler)
    await prices.current_price("RIO", company="Rio Tinto Group")
    prices._price_cache.clear()  # force a second real lookup, but symbol should be cached
    await prices.current_price("RIO", company="Rio Tinto Group")
    assert calls["search"] == 1


async def test_llm_chat_json_retries_then_succeeds(fake_httpx, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 2:
            return httpx.Response(429)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"ideas": []}'}}]},
        )

    fake_httpx(handler)
    result = await llm.extract_ideas("some newsletter text")
    assert result == []
    assert calls["n"] == 2


async def test_migrate_adds_currency_column_to_existing_table(tmp_path):
    """A DB created before the currency column existed must get it added on
    the next startup, not just fresh installs (CREATE TABLE IF NOT EXISTS
    only creates missing tables, not missing columns on ones that exist)."""
    import aiosqlite
    from app.db import _migrate

    db_path = tmp_path / "old.db"
    conn = await aiosqlite.connect(str(db_path))
    conn.row_factory = aiosqlite.Row
    try:
        await conn.execute(
            "CREATE TABLE performance (id INTEGER PRIMARY KEY, idea_id INTEGER, current_price REAL)"
        )
        await conn.commit()
        cols_before = {r["name"] for r in await conn.execute_fetchall("PRAGMA table_info(performance)")}
        assert "currency" not in cols_before

        await _migrate(conn)

        cols_after = {r["name"] for r in await conn.execute_fetchall("PRAGMA table_info(performance)")}
        assert "currency" in cols_after
    finally:
        await conn.close()


async def test_llm_chat_json_no_api_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    result = await llm.extract_ideas("text")
    assert result == []
