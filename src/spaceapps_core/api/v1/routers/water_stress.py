from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query

from ....clients.appeears import ECOSTRESS_WATER_STRESS_LAYERS
from ....schemas.common import Location
from ....services.appeears_jobs import submit_job

router = APIRouter(prefix="/water-stress", tags=["water-stress"])


@router.post(
    "/jobs",
    summary="Submit an ECOSTRESS Evaporative Stress Index (70 m) extraction job on AppEEARS",
    response_model=dict,
)
async def submit_water_stress_job(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    start: date = Query(..., description="ECOSTRESS data starts on 2018-07-10."),
    end: date = Query(...),
) -> dict:
    return await submit_job(
        source="appeears_ecostress",
        layers=ECOSTRESS_WATER_STRESS_LAYERS,
        location=Location(lat=lat, lon=lon),
        start=start,
        end=end,
    )
