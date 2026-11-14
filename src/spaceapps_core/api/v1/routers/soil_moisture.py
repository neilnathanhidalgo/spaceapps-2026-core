from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query

from ....clients.appeears import SMAP_SOIL_MOISTURE_LAYERS
from ....schemas.common import Location
from ....services.appeears_jobs import submit_job

router = APIRouter(prefix="/soil-moisture", tags=["soil-moisture"])


@router.post(
    "/jobs",
    summary="Submit a SMAP soil moisture extraction job on AppEEARS",
    response_model=dict,
)
async def submit_soil_moisture_job(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    start: date = Query(...),
    end: date = Query(...),
) -> dict:
    return await submit_job(
        source="appeears_smap",
        layers=SMAP_SOIL_MOISTURE_LAYERS,
        location=Location(lat=lat, lon=lon),
        start=start,
        end=end,
    )
