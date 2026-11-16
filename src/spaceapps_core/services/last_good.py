"""Last real answer per point, served when an upstream fails or stalls.

The app's demo plots must keep working on stage even if NASA POWER,
SoilGrids or Open-Meteo hiccup. Every successful answer is stored without
expiry under the exact request; when computing a new one fails (or takes
longer than `timeout_s`), the stored one is returned instead. It is always
a real answer for that same point, computed earlier: `generated_at` in the
body says when, and the router flags it with the `X-Served-From` header.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from ..core.cache import get_cache, make_key
from ..core.errors import UpstreamError, UpstreamTimeout

logger = logging.getLogger(__name__)

Model = TypeVar("Model", bound=BaseModel)

FALLBACK_ERRORS = (UpstreamError, UpstreamTimeout, httpx.HTTPError, TimeoutError, OSError)
"""Upstream trouble. Bad requests and missing configuration are not hidden."""


async def last_good(
    namespace: str,
    params: dict[str, Any],
    compute: Callable[[], Awaitable[Model]],
    model: type[Model],
    *,
    timeout_s: float,
) -> tuple[Model, bool]:
    """Fresh answer, or the last real one for the same request.

    Only when a stored copy exists is the fresh one given `timeout_s`; the
    first answer for a point waits as long as it takes. Returns the answer
    and whether it came from the stored copy.
    """
    key = make_key(f"last-good:{namespace}", params)
    stored = get_cache().get(key)
    try:
        # Sin copia guardada no hay a qué volver: se espera lo que tarde.
        fresh = await (
            compute() if stored is None else asyncio.wait_for(compute(), timeout=timeout_s)
        )
    except FALLBACK_ERRORS as error:
        if stored is None:
            raise
        logger.warning("Serving the last good %s answer: %s", namespace, error)
        return model.model_validate_json(stored), True
    get_cache().set(key, fresh.model_dump_json())
    return fresh, False
