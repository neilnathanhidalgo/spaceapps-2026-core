from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

import httpx
from fastapi import APIRouter

from ....clients.gaez import GAEZ_IMAGE_SERVER_URL
from ....clients.open_meteo import OPEN_METEO_ARCHIVE_URL
from ....clients.ornl_modis import NDVI_BAND, NDVI_PRODUCT, ORNL_MODIS_BASE_URL
from ....clients.soilgrids import SOILGRIDS_BASE_URL
from ....core.config import get_settings
from ....schemas.common import SourceHealth, SourcesHealth

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness check")
async def health() -> dict:
    return {"status": "ok"}


async def _timed_get(
    name: str,
    url: str,
    *,
    params: dict | None = None,
    method: str = "GET",
    timeout: float = 10.0,
    ok_status_min: int = 200,
    ok_status_max: int = 299,
) -> SourceHealth:
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.request(method, url, params=params)
        latency = (time.perf_counter() - t0) * 1000
        if ok_status_min <= r.status_code <= ok_status_max:
            return SourceHealth(name=name, status="ok", latency_ms=latency)
        return SourceHealth(
            name=name,
            status="error",
            latency_ms=latency,
            message=f"HTTP {r.status_code}",
        )
    except Exception as e:
        return SourceHealth(name=name, status="error", message=str(e))


async def _probe_power() -> SourceHealth:
    return await _timed_get(
        "power",
        "https://power.larc.nasa.gov/api/temporal/climatology/point",
        params={
            "parameters": "T2M",
            "community": "AG",
            "longitude": -80.63,
            "latitude": -5.19,
            "format": "JSON",
        },
    )


async def _probe_open_meteo() -> SourceHealth:
    return await _timed_get(
        "open_meteo",
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": -5.19,
            "longitude": -80.63,
            "daily": "temperature_2m_max",
            "forecast_days": 1,
        },
    )


async def _probe_era5() -> SourceHealth:
    return await _timed_get(
        "era5",
        f"{OPEN_METEO_ARCHIVE_URL}/archive",
        params={
            "latitude": -5.19,
            "longitude": -80.63,
            "start_date": "2024-01-01",
            "end_date": "2024-01-01",
            "daily": "temperature_2m_max",
            "models": "era5",
        },
    )


async def _probe_appeears() -> SourceHealth:
    settings = get_settings()
    if not settings.earthdata_configured:
        return SourceHealth(
            name="appeears",
            status="not_configured",
            message="EARTHDATA_USERNAME/PASSWORD unset",
        )
    return await _timed_get(
        "appeears",
        "https://appeears.earthdatacloud.nasa.gov/api/product",
        timeout=15.0,
    )


async def _probe_earthdata() -> SourceHealth:
    settings = get_settings()
    if not settings.earthdata_configured:
        return SourceHealth(
            name="earthdata",
            status="not_configured",
            message="EARTHDATA_USERNAME/PASSWORD unset",
        )
    return await _timed_get(
        "earthdata",
        "https://cmr.earthdata.nasa.gov/search/collections.json",
        params={"short_name": "GPM_3IMERGDF", "page_size": 1},
        timeout=15.0,
    )


async def _probe_nex_gddp() -> SourceHealth:
    return await _timed_get(
        "nex_gddp",
        "https://nex-gddp-cmip6.s3.amazonaws.com/",
        method="HEAD",
        ok_status_min=200,
        ok_status_max=499,
    )


async def _probe_gaez() -> SourceHealth:
    return await _timed_get("fao_gaez", GAEZ_IMAGE_SERVER_URL, params={"f": "json"}, timeout=15.0)


async def _probe_soilgrids() -> SourceHealth:
    return await _timed_get(
        "soilgrids",
        f"{SOILGRIDS_BASE_URL}/properties/query",
        params={"lon": -80.60, "lat": -5.25, "property": "soc", "depth": "0-5cm", "value": "mean"},
        timeout=20.0,
    )


async def _probe_ornl_modis() -> SourceHealth:
    return await _timed_get(
        "ornl_modis",
        f"{ORNL_MODIS_BASE_URL}/{NDVI_PRODUCT}/subset",
        params={
            "latitude": -5.19,
            "longitude": -80.63,
            "startDate": "A2023001",
            "endDate": "A2023017",
            "band": NDVI_BAND,
            "kmAboveBelow": 0,
            "kmLeftRight": 0,
        },
        timeout=20.0,
    )


SOURCE_PROBES: list[Callable[[], Awaitable[SourceHealth]]] = [
    _probe_power,
    _probe_open_meteo,
    _probe_era5,
    _probe_appeears,
    _probe_earthdata,
    _probe_nex_gddp,
    _probe_gaez,
    _probe_soilgrids,
    _probe_ornl_modis,
]


async def probe_sources() -> list[SourceHealth]:
    results = await asyncio.gather(*(probe() for probe in SOURCE_PROBES), return_exceptions=True)
    return [
        SourceHealth(name="unknown", status="error", message=str(res))
        if isinstance(res, BaseException)
        else res
        for res in results
    ]


@router.get(
    "/health/sources",
    response_model=SourcesHealth,
    summary="Probe every upstream data source in parallel",
)
async def health_sources() -> SourcesHealth:
    return SourcesHealth(sources=await probe_sources())
