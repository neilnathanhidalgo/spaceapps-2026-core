from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator

import pytest

os.environ.setdefault("CACHE_DIR", tempfile.mkdtemp(prefix="spaceapps-cache-"))
os.environ.setdefault("CORS_ORIGINS", "*")


@pytest.fixture(autouse=True)
def _clear_disk_cache() -> Iterator[None]:
    """Keep tests independent: wipe the on-disk cache around every test."""
    from spaceapps_core.core.cache import get_cache

    get_cache().clear()
    yield
    get_cache().clear()


@pytest.fixture
def client() -> Iterator:
    from fastapi.testclient import TestClient

    from spaceapps_core.main import create_app

    with TestClient(create_app()) as c:
        yield c
