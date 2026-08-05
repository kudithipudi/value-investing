"""Single LLM client for the app. All OpenRouter calls go through this module.

Prompts are designed to be robust: the extraction prompt returns strict JSON,
and callers parse defensively. Model, temperature, and timeout come from config.
"""

import json
import logging
import re
from typing import Any

import httpx

from app.config import get_settings
from app.services.http_utils import with_retry

logger = logging.getLogger(__name__)

_EXTRACT_SYSTEM = """You are a careful analyst reading an issue of the Graham & Doddsville newsletter,
published by Columbia Business School students. It contains investor interviews and formal stock pitches.

Your job: extract every investment IDEA mentioned, of two kinds:
- "pitch": a formal, argued stock pitch (usually a named challenge such as the Pershing Square Challenge,
  Stock Pitch Challenge, etc.), with a clear thesis, often an entry price and sometimes a target price.
- "position": a stock an interviewed investor mentions owning/considering in passing, with at least a
  one-sentence rationale. Ignore purely historical references and companies named only for context.

For each idea return a JSON object with these fields:
{"ticker": "e.g. AAPL or null if unknown",
 "company": "official company name",
 "kind": "pitch" or "position",
 "direction": "long" | "short" | "long/short" | null,
 "thesis": "2-4 sentence summary of the thesis as stated",
 "challenge": "name of pitch challenge if it is a formal pitch, else null",
 "author": "student name or investor/firm name",
 "price_at_pitch": number or null if a price is not stated,
 "target_price": number or null,
 "pitch_date": "approximate date or season the pitch was made, e.g. 2024-04, or null"}

Return ONLY a JSON object: {"ideas": [ <idea objects as described> ]}.
If there are no ideas in the given text, return {"ideas": []}."""

_VERDICT_SYSTEM = """You are an investment analyst evaluating whether a past stock pitch "worked".
You will be given a pitch thesis (long or short) and, where available, its actual price performance.
Decide whether the thesis played out, partially played out, or failed.

Return ONLY a JSON object:
{"verdict": "worked" | "partial" | "failed" | "inconclusive",
 "explanation": "2-4 sentences explaining the judgement, citing the return and thesis dynamics",
 "confidence": "high" | "medium" | "low"}

Rules:
- If price data is provided, weigh return direction against the stated direction (long vs short).
- If no price data, base the verdict on whether the thesis events occurred; mark confidence low.
- Do not fabricate facts. If you cannot tell, use "inconclusive"."""

_BEST_PICK_SYSTEM = """You are a value-investing analyst. Given the fresh investment ideas from the most recent
Graham & Doddsville newsletter, rank them for a hypothetical long-only investor TODAY.
Score each idea 1-100 on: quality of thesis, margin of safety / valuation, durability of the
business, and distance-to-target (more room to run = higher). Penalize ideas that have already
moved toward the target. Prefer liquid, long ideas; be conservative for shorts.

Return ONLY a JSON object: {"picks": [ one object per idea, ordered best first: {"ticker": "...", "company": "...", "score": 85, "rationale": "2-3 sentences", "action": "buy | watch | avoid"} ]}"""


async def _chat_json(system: str, user: str) -> Any:
    settings = get_settings()
    if not settings.openrouter_api_key:
        logger.warning("No OPENROUTER_API_KEY set; skipping LLM call")
        return None
    payload = {
        "model": settings.llm_model,
        "temperature": settings.llm_temperature,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": {"type": "json_object"},
    }
    async def _do_request():
        async with httpx.AsyncClient(timeout=settings.llm_timeout) as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.openrouter_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            return resp

    try:
        resp = await with_retry(_do_request)
    except (httpx.HTTPStatusError, httpx.TransportError) as exc:
        logger.error("OpenRouter request failed: %s", exc)
        return None
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    return _parse_json(content)


def _parse_json(content: str) -> Any:
    """OpenRouter JSON objects sometimes arrive wrapped in ```json fences."""
    content = content.strip()
    fenced = re.match(r"```(?:json)?\s*(.*?)\s*```", content, re.DOTALL)
    if fenced:
        content = fenced.group(1)
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start = content.find("[")
        obj = content.find("{")
        idx = min(i for i in (start, obj) if i != -1) if (start != -1 and obj != -1) else (start if start != -1 else obj)
        if idx != -1:
            try:
                return json.loads(content[idx:])
            except json.JSONDecodeError:
                pass
        logger.error("Could not parse LLM JSON output: %r", content[:500])
        return None


async def extract_ideas(text: str) -> list[dict]:
    """Extract structured ideas from a section of newsletter text."""
    result = await _chat_json(_EXTRACT_SYSTEM, text[:9000])
    if isinstance(result, dict) and isinstance(result.get("ideas"), list):
        return result["ideas"]
    return []


async def judge_idea(thesis: str, direction: str | None, return_pct: float | None) -> dict | None:
    user = f"Direction: {direction or 'unknown'}\nThesis:\n{thesis[:4000]}"
    if return_pct is not None:
        user += f"\nPrice performance since pitch: {return_pct:+.1f}%"
    else:
        user += "\nPrice performance since pitch: not available"
    result = await _chat_json(_VERDICT_SYSTEM, user)
    if isinstance(result, dict):
        return result
    return None


async def score_best_picks(ideas: list[dict]) -> list[dict]:
    """Rank fresh ideas from the latest issue. Returns list of scored picks."""
    if not ideas:
        return []
    user = "Fresh ideas (JSON):\n" + json.dumps(ideas)
    result = await _chat_json(_BEST_PICK_SYSTEM, user)
    if isinstance(result, dict) and isinstance(result.get("picks"), list):
        return result["picks"]
    return []
