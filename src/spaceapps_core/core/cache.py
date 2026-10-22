from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import diskcache

from .config import get_settings

_cache: diskcache.Cache | None = None


def get_cache() -> diskcache.Cache:
    global _cache
    if _cache is None:
        settings = get_settings()
        path = Path(settings.cache_dir)
        path.mkdir(parents=True, exist_ok=True)
        _cache = diskcache.Cache(str(path))
    return _cache


def make_key(namespace: str, params: dict[str, Any]) -> str:
    payload = json.dumps(params, sort_keys=True, default=str)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"{namespace}:{digest}"


def cached_or_set(key: str, factory, ttl: int):
    cache = get_cache()
    hit = cache.get(key)
    if hit is not None:
        return hit, True
    value = factory()
    cache.set(key, value, expire=ttl)
    return value, False


async def async_cached_or_set(key: str, factory, ttl: int):
    cache = get_cache()
    hit = cache.get(key)
    if hit is not None:
        return hit, True
    value = await factory()
    cache.set(key, value, expire=ttl)
    return value, False
