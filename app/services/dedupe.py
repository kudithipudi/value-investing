"""Detects LLM-chunking fragments: long pitch write-ups get split into several
text sections before extraction (see extractor.split_sections' max_chars), and
when one pitch spans multiple sections, the LLM re-extracts "an idea" from
each fragment — same issue, same ticker, same author, same call, but several
DB rows with different partial thesis text.

Merge key requires a recoverable author on both sides: rows where the LLM
couldn't attribute an author are left alone, since merging those risks
conflating two different people's independent mentions of the same stock.
"""

import re

_PARENTHETICAL = re.compile(r"\(.*?\)")
_NULLISH = {"", "null", "none", "n/a"}


def normalize_author(author: str | None) -> str | None:
    if not author:
        return None
    cleaned = _PARENTHETICAL.sub("", author).strip().lower()
    return None if cleaned in _NULLISH else cleaned


def _normalize_field(value: str | None) -> str | None:
    """Treats the literal strings the LLM sometimes emits instead of JSON
    null ("null", "none", "n/a") as genuinely missing, same as an empty value.
    """
    if not value:
        return None
    cleaned = value.strip()
    return None if cleaned.lower() in _NULLISH else cleaned


def fragment_key(
    *,
    issue_id,
    kind: str | None,
    ticker: str | None,
    company: str | None,
    direction: str | None,
    author: str | None,
) -> tuple | None:
    """Key identifying probable fragments of the same idea within one issue.

    Returns None when there's no recoverable ticker/company or author to key
    on — such rows are never merged.
    """
    norm_ticker = _normalize_field(ticker)
    ident = norm_ticker.upper() if norm_ticker else None
    if ident is None:
        norm_company = _normalize_field(company)
        ident = f"company:{norm_company.lower()}" if norm_company else None
    if ident is None:
        return None
    norm_author = normalize_author(author)
    if norm_author is None:
        return None
    return (issue_id, ident, direction, kind, norm_author)


def dedupe_new_ideas(ideas: list[dict]) -> list[dict]:
    """Collapse same-batch fragments before insert, keeping the longest thesis
    per group. `ideas` is a single issue's freshly-extracted idea dicts (not
    yet in the DB), so issue_id is constant across the whole batch."""
    best: dict[tuple, dict] = {}
    order: list[tuple] = []
    passthrough: list[dict] = []
    for idea in ideas:
        key = fragment_key(
            issue_id=0,
            kind=idea.get("kind"),
            ticker=idea.get("ticker"),
            company=idea.get("company"),
            direction=idea.get("direction"),
            author=idea.get("author"),
        )
        if key is None:
            passthrough.append(idea)
            continue
        current = best.get(key)
        if current is None:
            order.append(key)
            best[key] = idea
        elif len(idea.get("thesis") or "") > len(current.get("thesis") or ""):
            best[key] = idea
    return [best[k] for k in order] + passthrough
