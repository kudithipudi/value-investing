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
    price, as_of = await prices.current_price("AAPL")
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
    price, as_of = await prices.current_price("NOPE")
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
    price, as_of = await prices.current_price("RIO", company="Rio Tinto Group")
    assert price == 123.45


async def test_prices_current_price_search_no_match_stays_none(fake_httpx):
    def handler(request):
        if "/finance/search" in str(request.url):
            return httpx.Response(200, json=_SEARCH_NO_MATCH)
        return httpx.Response(200, json=_EMPTY_CHART)

    fake_httpx(handler)
    price, as_of = await prices.current_price("XXXX", company="Some Untraceable Co")
    assert price is None


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


async def test_llm_chat_json_no_api_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    result = await llm.extract_ideas("text")
    assert result == []
