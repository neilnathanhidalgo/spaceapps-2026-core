"""Fixtures shared by the unit tests.

Unit tests never touch the network, so Earthdata is off by default: anything
that needs credentials has to ask for `earthdata_env` on purpose.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from spaceapps_core.clients.appeears import TOKEN_CACHE_KEY
from spaceapps_core.clients.earthdata import EarthdataClient
from spaceapps_core.core.cache import get_cache
from spaceapps_core.core.config import get_settings


def _reset_earthdata_session() -> None:
    get_settings.cache_clear()
    get_cache().delete(TOKEN_CACHE_KEY)
    EarthdataClient._logged_in = False


@pytest.fixture(autouse=True)
def no_earthdata_env(monkeypatch) -> Iterator[None]:
    """No Earthdata credentials, whatever the developer has in `.env`."""
    monkeypatch.setenv("EARTHDATA_USERNAME", "")
    monkeypatch.setenv("EARTHDATA_PASSWORD", "")
    _reset_earthdata_session()
    yield
    _reset_earthdata_session()


@pytest.fixture
def earthdata_env(monkeypatch) -> Iterator[None]:
    """Credentials that look real, for the clients that require them."""
    monkeypatch.setenv("EARTHDATA_USERNAME", "demo-user")
    monkeypatch.setenv("EARTHDATA_PASSWORD", "demo-pass")
    _reset_earthdata_session()
    yield
    _reset_earthdata_session()
