import hashlib
import logging
from pathlib import Path

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


async def download_pdf(url: str, pdf_dir: str | None = None) -> str | None:
    """Download a newsletter PDF to the pdf dir. Returns the stored filename."""
    settings = get_settings()
    target_dir = Path(pdf_dir or settings.pdf_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(
        timeout=120, follow_redirects=True, headers={"User-Agent": settings.user_agent}
    ) as client:
        resp = await client.get(url)
        if resp.status_code != 200:
            logger.warning("Download failed for %s: %s", url, resp.status_code)
            return None
        if "pdf" not in (resp.headers.get("content-type", "") or ""):
            logger.warning("Non-PDF response for %s: %s", url, resp.headers.get("content-type"))
            return None
        content = resp.content
        if not content.startswith(b"%PDF"):
            logger.warning("Response for %s is not a PDF", url)
            return None

    digest = hashlib.sha256(content).hexdigest()[:16]
    filename = f"{digest}.pdf"
    path = target_dir / filename
    if not path.exists():
        path.write_bytes(content)
    logger.info("Downloaded %s -> %s (%d bytes)", url, filename, len(content))
    return filename


async def head_pdf(url: str) -> bool:
    """Cheap existence check for a PDF URL."""
    settings = get_settings()
    async with httpx.AsyncClient(
        timeout=30, follow_redirects=True, headers={"User-Agent": settings.user_agent}
    ) as client:
        try:
            resp = await client.head(url)
            if resp.status_code in (200, 301, 302):
                return True
            resp = await client.get(url, headers={"Range": "bytes=0-64"})
            return resp.status_code == 200 and resp.content.startswith(b"%PDF")
        except httpx.HTTPError:
            return False
