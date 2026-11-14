from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Query

from ....clients.appeears import HLS_NDVI_LAYERS, MODIS_NDVI_LAYERS
from ....schemas.common import Location
from ....services.appeears_jobs import submit_job

router = APIRouter(prefix="/vegetation", tags=["vegetation"])

VegetationSensor = Literal["modis", "hls"]

_SENSORS = {
    "modis": ("appeears_modis", MODIS_NDVI_LAYERS),
    "hls": ("appeears_hls", HLS_NDVI_LAYERS),
}


@router.post(
    "/jobs",
    summary="Submit a vegetation index extraction job on AppEEARS (MODIS or HLS)",
    response_model=dict,
)
async def submit_vegetation_job(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    start: date = Query(...),
    end: date = Query(...),
    sensor: VegetationSensor = Query(
        "modis",
        description=(
            "`modis`: MOD13Q1 NDVI/EVI, 250 m, 16-day composites since 2000. "
            "`hls`: Harmonized Landsat + Sentinel-2 NDVI, 30 m, every 2-3 days since 2013."
        ),
    ),
) -> dict:
    source, layers = _SENSORS[sensor]
    return await submit_job(
        source=source,
        layers=layers,
        location=Location(lat=lat, lon=lon),
        start=start,
        end=end,
    )
