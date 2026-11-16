from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel

from spaceapps_core.core.errors import InvalidRequestError, UpstreamError
from spaceapps_core.services.last_good import last_good


class _Answer(BaseModel):
    value: int


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    from spaceapps_core.core import cache
    from spaceapps_core.core.config import get_settings

    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    get_settings.cache_clear()
    monkeypatch.setattr(cache, "_cache", None)
    yield
    get_settings.cache_clear()
    monkeypatch.setattr(cache, "_cache", None)


def _run(coro):
    return asyncio.run(coro)


async def _ok(value: int) -> _Answer:
    return _Answer(value=value)


async def _fails() -> _Answer:
    raise UpstreamError("NASA POWER is down")


async def _slow() -> _Answer:
    await asyncio.sleep(1)
    return _Answer(value=99)


def test_stores_the_fresh_answer_and_serves_it_when_the_upstream_fails() -> None:
    params = {"lat": -4.865, "lon": -80.72}
    fresh, from_store = _run(last_good("t", params, lambda: _ok(1), _Answer, timeout_s=5))
    assert (fresh.value, from_store) == (1, False)

    served, from_store = _run(last_good("t", params, _fails, _Answer, timeout_s=5))
    assert (served.value, from_store) == (1, True)


def test_serves_the_stored_answer_when_the_fresh_one_is_too_slow() -> None:
    params = {"lat": 1}
    _run(last_good("t", params, lambda: _ok(1), _Answer, timeout_s=5))

    served, from_store = _run(last_good("t", params, _slow, _Answer, timeout_s=0.05))
    assert (served.value, from_store) == (1, True)


def test_without_a_stored_answer_waits_and_errors_still_surface() -> None:
    answer, from_store = _run(last_good("t", {"a": 1}, _slow, _Answer, timeout_s=0.05))
    assert (answer.value, from_store) == (99, False)

    with pytest.raises(UpstreamError):
        _run(last_good("t", {"a": 2}, _fails, _Answer, timeout_s=5))


def test_bad_requests_are_not_hidden() -> None:
    params = {"a": 3}
    _run(last_good("t", params, lambda: _ok(1), _Answer, timeout_s=5))

    async def bad() -> _Answer:
        raise InvalidRequestError("unknown crop")

    with pytest.raises(InvalidRequestError):
        _run(last_good("t", params, bad, _Answer, timeout_s=5))
