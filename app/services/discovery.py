"""Discovery of newsletter issues not yet in the local catalog.

The Columbia listing page 403s for bots, so new issues are discovered from:
  1. the public grahamanddoddsville.net archive mirror (which lists links + seasons), and
  2. manual URL entry in the UI.
The mirror archive only covers up to ~Issue 33; anything newer is added via manual URL.
"""

import logging
import re
from urllib.parse import unquote

import httpx
from bs4 import BeautifulSoup

from app.config import get_settings

logger = logging.getLogger(__name__)

_LINK_RE = re.compile(r"Graham.*?Issue[^\d]*(\d+)", re.IGNORECASE)


def _season_from_text(text: str) -> str | None:
    text = " ".join(text.split())
    m = re.search(r"(Winter|Spring|Summer|Fall|Summer/Fall|Winter/Spring)?\s*(20\d\d)", text)
    if m:
        return f"{m.group(1) or ''} {m.group(2)}".strip()
    return None


def _issue_number_from_url(url: str) -> int | None:
    decoded = unquote(url)
    m = re.search(r"Issue\D+(\d+)", decoded, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r"Issue[_-]?(\d+)", decoded, re.IGNORECASE)
    return int(m.group(1)) if m else None


async def scan_mirror_archive() -> list[dict]:
    """Fetch the grahamanddoddsville.net archive page and return candidate issues."""
    settings = get_settings()
    candidates: list[dict] = []
    try:
        async with httpx.AsyncClient(
            timeout=60, follow_redirects=True, headers={"User-Agent": settings.user_agent}
        ) as client:
            resp = await client.get(settings.mirror_archive_url)
            if resp.status_code != 200:
                logger.warning("Mirror archive returned %s", resp.status_code)
                return candidates
        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not href.lower().endswith(".pdf"):
                continue
            text = a.get_text(" ", strip=True)
            candidates.append(
                {
                    "url": href,
                    "title": text,
                    "issue_number": _issue_number_from_url(href),
                    "season": _season_from_text(text),
                }
            )
    except Exception as exc:  # noqa: BLE001 - discovery must never crash the app
        logger.error("Mirror scan failed: %s", exc)
    return candidates


def normalize_url(raw: str) -> str | None:
    url = raw.strip()
    if url.lower().startswith("http://") or url.lower().startswith("https://"):
        return url
    if url.lower().startswith("www."):
        return "https://" + url
    # Bare domain path like "business.columbia.edu/...pdf"
    if re.match(r"^[a-z0-9-]+(\.[a-z0-9-]+)+[/:]", url, re.IGNORECASE):
        return "https://" + url
    return None
