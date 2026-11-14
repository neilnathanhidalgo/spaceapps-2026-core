from __future__ import annotations

from fastapi import APIRouter, Query

from ....clients.appeears import (
    SRTM_ACQUISITION_END,
    SRTM_ACQUISITION_START,
    SRTM_ELEVATION_LAYERS,
)
from ....schemas.common import Location
from ....services.appeears_jobs import submit_job

router = APIRouter(prefix="/terrain", tags=["terrain"])


@router.post(
    "/jobs",
    summary="Submit an SRTM elevation (30 m) extraction job on AppEEARS",
    response_model=dict,
)
async def submit_terrain_job(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
) -> dict:
    return await submit_job(
        source="appeears_srtm",
        layers=SRTM_ELEVATION_LAYERS,
        location=Location(lat=lat, lon=lon),
        start=SRTM_ACQUISITION_START,
        end=SRTM_ACQUISITION_END,
    )
