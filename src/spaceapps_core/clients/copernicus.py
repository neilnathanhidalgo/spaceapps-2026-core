"""Copernicus Data Space STAC search for Sentinel-2 scenes.

Only scene discovery is implemented for now; actual asset download and NDVI
computation are left as TODO.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from ..core.cache import async_cached_or_set, make_key
from ..core.config import get_settings
from ..core.errors import UpstreamError
from ..core.http import async_client, request_with_retry
from ..schemas.common import Location
from .base import BaseClient

COPERNICUS_STAC_URL = "https://catalogue.dataspace.copernicus.eu/stac"
SENTINEL2_COLLECTION = "SENTINEL-2"


class CopernicusClient(BaseClient):
    source_name = "copernicus"

    def __init__(self, *, base_url: str = COPERNICUS_STAC_URL) -> None:
        self.base_url = base_url

    async def search_sentinel2(
        self,
        *,
        location: Location,
        start: date,
        end: date,
        max_cloud_cover: float | None = 50.0,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search Sentinel-2 scenes intersecting a point for a date range."""

        settings = get_settings()
        bbox = _point_to_bbox(location.lon, location.lat, delta=0.01)
        datetime_range = f"{start.isoformat()}T00:00:00Z/{end.isoformat()}T23:59:59Z"

        body: dict[str, Any] = {
            "collections": [SENTINEL2_COLLECTION],
            "bbox": bbox,
            "datetime": datetime_range,
            "limit": limit,
        }
        if max_cloud_cover is not None:
            body["filter-lang"] = "cql2-json"
            body["filter"] = {
                "op": "<=",
                "args": [{"property": "eo:cloud_cover"}, max_cloud_cover],
            }

        cache_key = make_key("copernicus:sentinel2_search", body)

        async def fetch() -> dict[str, Any]:
            async with async_client(base_url=self.base_url) as c:
                r = await request_with_retry(c, "POST", "/search", json=body)
                if r.status_code >= 400:
                    raise UpstreamError(
                        f"Copernicus STAC search failed HTTP {r.status_code}: {r.text[:200]}"
                    )
                return r.json()

        data, _ = await async_cached_or_set(cache_key, fetch, settings.cache_ttl_satellite)

        features = data.get("features", [])
        return [_simplify_feature(f) for f in features]


def _point_to_bbox(lon: float, lat: float, *, delta: float) -> list[float]:
    return [lon - delta, lat - delta, lon + delta, lat + delta]


def _simplify_feature(feature: dict[str, Any]) -> dict[str, Any]:
    props = feature.get("properties", {}) or {}
    return {
        "id": feature.get("id"),
        "datetime": props.get("datetime"),
        "cloud_cover": props.get("eo:cloud_cover"),
        "platform": props.get("platform"),
        "collection": feature.get("collection"),
        "assets": list((feature.get("assets") or {}).keys()),
        "self_href": _self_href(feature),
    }


def _self_href(feature: dict[str, Any]) -> str | None:
    for link in feature.get("links") or []:
        if link.get("rel") == "self":
            return link.get("href")
    return None
