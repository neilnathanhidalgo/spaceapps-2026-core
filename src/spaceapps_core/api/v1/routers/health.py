from __future__ import annotations

import asyncio
import time

import httpx
from fastapi import APIRouter

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


async def _probe_copernicus() -> SourceHealth:
    return await _timed_get(
        "copernicus",
        "https://catalogue.dataspace.copernicus.eu/stac/collections",
    )


@router.get(
    "/health/sources",
    response_model=SourcesHealth,
    summary="Probe every upstream data source in parallel",
)
async def health_sources() -> SourcesHealth:
    probes = [
        _probe_power(),
        _probe_open_meteo(),
        _probe_appeears(),
        _probe_earthdata(),
        _probe_nex_gddp(),
        _probe_copernicus(),
    ]
    results = await asyncio.gather(*probes, return_exceptions=True)
    sources: list[SourceHealth] = []
    for res in results:
        if isinstance(res, Exception):
            sources.append(SourceHealth(name="unknown", status="error", message=str(res)))
        else:
            sources.append(res)
    return SourcesHealth(sources=sources)
