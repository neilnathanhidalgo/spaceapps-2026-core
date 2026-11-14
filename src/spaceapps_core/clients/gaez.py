"""FAO GAEZ v4 crop suitability, read point by point from FAO's ArcGIS ImageServer.

Each crop is a separate raster in the mosaic, so the client first resolves the
raster ids from the catalog and then samples one raster per crop.
"""

from __future__ import annotations

import asyncio
import json
import math
from typing import Any

import httpx

from ..core.cache import async_cached_or_set, make_key
from ..core.config import get_settings
from ..core.errors import InvalidRequestError, UpstreamError
from ..core.http import async_client, request_with_retry
from ..schemas.common import Location
from ..schemas.crop_suitability import CropSuitability, CropSuitabilityReport, GaezInputLevel
from .base import BaseClient

GAEZ_IMAGE_SERVER_URL = "https://gaez-services.fao.org/server/rest/services/res05/ImageServer"
BASELINE_PERIOD = "1981-2010"
SUITABILITY_SCALE = 10000.0
CELL_SIZE_DEG = 5 / 60
# FAO's shared server takes ~2 s per sample; keep our load on it bounded.
MAX_CONCURRENT_SAMPLES = 5

_INPUT_LEVELS: dict[str, str] = {"high": "High", "low": "Low"}

# Crops grown in the Piura pilot region, from the coastal valleys to the highlands.
DEFAULT_CROPS = [
    "Maize",
    "Wetland rice",
    "Dryland rice",
    "Cotton",
    "Sugarcane",
    "Banana",
    "Citrus",
    "Cassava",
    "Sweet potato",
    "Phaseolus bean",
    "Cowpea",
    "Groundnut",
    "Sorghum",
    "Coffee",
    "Cocoa",
    "White potato",
    "Onion",
    "Tomato",
    "Wheat",
    "Barley",
]


class GaezClient(BaseClient):
    source_name = "fao_gaez"

    def __init__(
        self,
        *,
        base_url: str = GAEZ_IMAGE_SERVER_URL,
        timeout: float | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout = timeout

    async def crop_suitability(
        self,
        location: Location,
        *,
        input_level: GaezInputLevel = "high",
        crops: list[str] | None = None,
    ) -> CropSuitabilityReport:
        """Rainfed suitability index (0-1) per crop for the 1981-2010 baseline climate."""

        catalog = await self._suitability_rasters(input_level)
        selected = _select_crops(catalog, crops or DEFAULT_CROPS)

        semaphore = asyncio.Semaphore(MAX_CONCURRENT_SAMPLES)
        async with async_client(base_url=self.base_url, timeout=self.timeout) as c:
            indices = await asyncio.gather(
                *(
                    self._sample(c, semaphore, location, raster_id)
                    for raster_id in selected.values()
                )
            )

        results = [
            CropSuitability(crop=crop, suitability_index=index)
            for crop, index in zip(selected, indices, strict=True)
        ]
        results.sort(
            key=lambda r: -1.0 if r.suitability_index is None else r.suitability_index,
            reverse=True,
        )
        return CropSuitabilityReport(
            location=location,
            period=BASELINE_PERIOD,
            input_level=input_level,
            crops=results,
        )

    async def _suitability_rasters(self, input_level: GaezInputLevel) -> dict[str, int]:
        where = (
            "sub_theme_name = 'Suitability Index' "
            "AND variable LIKE 'Suitability index%all land%' "
            f"AND year = '{BASELINE_PERIOD}' "
            "AND water_supply = 'Rainfed' "
            f"AND input_level = '{_INPUT_LEVELS[input_level]}'"
        )

        async def fetch() -> dict[str, int]:
            async with async_client(base_url=self.base_url, timeout=self.timeout) as c:
                data = await _get_json(
                    c,
                    "/query",
                    {"where": where, "outFields": "objectid,crop", "returnGeometry": "false"},
                )
            return {
                f["attributes"]["crop"]: int(f["attributes"]["objectid"])
                for f in data.get("features", [])
            }

        catalog, _ = await async_cached_or_set(
            make_key("gaez:catalog", {"where": where}),
            fetch,
            get_settings().cache_ttl_static,
        )
        if not catalog:
            raise UpstreamError("FAO GAEZ returned an empty suitability catalog.")
        return catalog

    async def _sample(
        self,
        c: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
        location: Location,
        raster_id: int,
    ) -> float | None:
        params = {
            "geometry": json.dumps(
                {"x": location.lon, "y": location.lat, "spatialReference": {"wkid": 4326}}
            ),
            "geometryType": "esriGeometryPoint",
            "mosaicRule": json.dumps(
                {"mosaicMethod": "esriMosaicLockRaster", "lockRasterIds": [raster_id]}
            ),
            "returnFirstValueOnly": "true",
        }

        async def fetch() -> dict[str, float | None]:
            async with semaphore:
                data = await _get_json(c, "/getSamples", params)
            samples = data.get("samples") or []
            return {"value": _to_index(samples[0].get("value")) if samples else None}

        sample, _ = await async_cached_or_set(
            make_key("gaez:sample", {"cell": _grid_cell(location), "raster_id": raster_id}),
            fetch,
            get_settings().cache_ttl_static,
        )
        return sample["value"]


def _select_crops(catalog: dict[str, int], requested: list[str]) -> dict[str, int]:
    by_lower = {name.lower(): name for name in catalog}
    unknown = [crop for crop in requested if crop.lower() not in by_lower]
    if unknown:
        raise InvalidRequestError(
            f"Unknown GAEZ crops: {unknown}.",
            details={"available": sorted(catalog)},
        )
    names = [by_lower[crop.lower()] for crop in requested]
    return {name: catalog[name] for name in dict.fromkeys(names)}


def _grid_cell(location: Location) -> tuple[int, int]:
    return (
        math.floor(location.lat / CELL_SIZE_DEG),
        math.floor(location.lon / CELL_SIZE_DEG),
    )


def _to_index(raw: Any) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value < 0:
        return None
    return round(value / SUITABILITY_SCALE, 4)


async def _get_json(c: httpx.AsyncClient, path: str, params: dict[str, str]) -> dict[str, Any]:
    r = await request_with_retry(c, "GET", path, params={**params, "f": "json"})
    if r.status_code >= 400:
        raise UpstreamError(f"FAO GAEZ returned HTTP {r.status_code}: {r.text[:200]}")
    data = r.json()
    # ArcGIS reports failures inside a 200 response.
    if "error" in data:
        raise UpstreamError(f"FAO GAEZ error: {data['error'].get('message')}")
    return data
