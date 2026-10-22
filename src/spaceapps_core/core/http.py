from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .config import get_settings
from .errors import UpstreamError, UpstreamTimeout

_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


class RetryableStatus(Exception):
    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        super().__init__(f"Retryable upstream status: {response.status_code}")


def build_async_client(
    *,
    base_url: str | None = None,
    timeout: float | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.AsyncClient:
    settings = get_settings()
    return httpx.AsyncClient(
        base_url=base_url or "",
        timeout=timeout or settings.http_timeout,
        headers=headers or {},
        follow_redirects=True,
    )


@asynccontextmanager
async def async_client(
    *,
    base_url: str | None = None,
    timeout: float | None = None,
    headers: dict[str, str] | None = None,
) -> AsyncIterator[httpx.AsyncClient]:
    client = build_async_client(base_url=base_url, timeout=timeout, headers=headers)
    try:
        yield client
    finally:
        await client.aclose()


async def request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    retries: int | None = None,
    **kwargs,
) -> httpx.Response:
    settings = get_settings()
    attempts = retries if retries is not None else settings.http_retries

    retryer = AsyncRetrying(
        stop=stop_after_attempt(max(1, attempts)),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=10),
        retry=retry_if_exception_type(
            (httpx.TransportError, httpx.TimeoutException, RetryableStatus)
        ),
        reraise=True,
    )

    try:
        async for attempt in retryer:
            with attempt:
                response = await client.request(method, url, **kwargs)
                if response.status_code in _RETRYABLE_STATUS:
                    raise RetryableStatus(response)
                return response
    except httpx.TimeoutException as e:
        raise UpstreamTimeout(f"Request to {url} timed out.") from e
    except httpx.TransportError as e:
        raise UpstreamError(f"Transport error contacting {url}: {e}") from e
    except RetryableStatus as e:
        return e.response

    raise UpstreamError(f"Unknown error requesting {url}.")
