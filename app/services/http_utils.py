"""Shared retry helper for outbound HTTP calls (Yahoo Finance, OpenRouter)."""

import asyncio
import logging
from typing import Awaitable, Callable, TypeVar

import httpx

logger = logging.getLogger(__name__)

T = TypeVar("T")

_DEFAULT_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


async def with_retry(
    fn: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    base_delay: float = 0.5,
    retry_statuses: frozenset[int] = _DEFAULT_RETRY_STATUSES,
) -> T:
    """Call `fn()` with exponential backoff on transient failures.

    Retries httpx.HTTPStatusError with a status in `retry_statuses` and
    httpx.TransportError (timeouts, connection resets). Anything else
    (e.g. a 404 for an unknown ticker) is raised immediately.
    """
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            return await fn()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in retry_statuses or attempt == attempts - 1:
                raise
            last_exc = exc
        except httpx.TransportError as exc:
            if attempt == attempts - 1:
                raise
            last_exc = exc
        delay = base_delay * (2**attempt)
        logger.warning("Retrying after transient error (attempt %d/%d): %s", attempt + 1, attempts, last_exc)
        await asyncio.sleep(delay)
    raise last_exc  # pragma: no cover - unreachable, loop always returns or raises
