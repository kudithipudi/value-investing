"""PDF text extraction and section splitting.

Each issue is a sequence of interviews and formal stock pitches. We split the raw
text into "pitch-ish" and "interview" chunks so the LLM only processes the passages
most likely to contain investment ideas. The split is heuristic (headline markers);
the LLM decides what is actually an idea and what is not.
"""

import logging
import re
from pathlib import Path

from pypdf import PdfReader

logger = logging.getLogger(__name__)

_PITCH_MARKERS = re.compile(
    r"(?i)(stock pitch|investment idea|investment opportunity|"
    r"pershing square (challenge|competition)|student pitch|"
    r"stock pitch challenge|the pitch|long (thesis|idea)|short (thesis|idea))"
)
_INTERVIEW_MARKERS = re.compile(
    r"(?i)(interview with|we spoke with|featuring|our conversation with|"
    r"in this issue, we|interview:)",
)
_PAGE_BREAK = re.compile(r"\f")

# High-signal patterns that indicate a passage likely names an investment idea.
_IDEA_SIGNAL = re.compile(
    r"(?i)(trading at|trades at|traded at|\bP/E\b|earnings|margin of safety|"
    r"upside|downside|fair value|intrinsic value|compounder|we (bought|own|like|"
    r"think|believe|see)|long |short |stock price|share price|"
    r"\b[A-Z]{2,5}\b.*\$|catalyst)"
)


def extract_pdf_text(pdf_path: str | Path) -> str:
    path = Path(pdf_path)
    reader = PdfReader(str(path))
    parts: list[str] = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception as exc:  # noqa: BLE001 - tolerate corrupt pages
            logger.warning("Page extraction failed in %s: %s", path, exc)
    return _PAGE_BREAK.sub("\n", "\n".join(parts))


def split_sections(text: str, max_chars: int = 9000) -> list[dict]:
    """Split newsletter text into sections tagged as pitch-ish or interview-ish.

    Consecutive fragments belonging to the same interview are merged up to max_chars
    so the LLM is called once per meaningful block rather than once per page fragment.
    """
    lines = text.splitlines()
    sections: list[dict] = []
    current: list[str] = []
    current_is_pitch = False

    def flush():
        nonlocal current
        body = "\n".join(current).strip()
        if len(body) >= 400:
            sections.append({"is_pitch": current_is_pitch, "text": body})
        current = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _PITCH_MARKERS.search(stripped) and len(stripped) < 120:
            flush()
            current_is_pitch = True
            current = [stripped]
            continue
        current.append(stripped)
        if sum(len(l) for l in current) > max_chars:
            flush()
    flush()

    # A merged block is a pitch if any short line inside looked like a pitch heading
    # (e.g. "STOCK PITCH CHALLENGE" or "LONG THESIS"). Flowing interview prose rarely
    # produces such short all-caps lines, so this is a safe over-approximation.
    for s in sections:
        has_pitch_heading = any(
            len(l) < 120 and _PITCH_MARKERS.search(l) for l in s["text"].splitlines()
        )
        s["is_pitch"] = has_pitch_heading
    return sections


def has_idea_signal(text: str) -> bool:
    """Cheap pre-filter: does this passage plausibly name an investment idea?"""
    return bool(_IDEA_SIGNAL.search(text))


def _looks_like_heading(line: str) -> bool:
    if not line:
        return False
    if line.isupper() and len(line) < 100:
        return True
    if re.match(r"^[A-Z][a-zA-Z]+[ &•|\-\u2013\u2014][A-Za-z]", line) and len(line) < 80:
        # E.g. "Jim Chanos", "Pershing Square Challenge" — short capitalized lines
        return line.count(" ") <= 6
    return False
