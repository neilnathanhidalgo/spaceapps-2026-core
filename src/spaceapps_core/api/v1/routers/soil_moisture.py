from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query

from ....clients.appeears import SMAP_SOIL_MOISTURE_LAYERS, AppEEARSClient
from ....schemas.common import Location
from ....services.appeears_jobs import JobRegistryEntry, register_job

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
    location = Location(lat=lat, lon=lon)
    client = AppEEARSClient()
    task_id = await client.submit_point_task(
        location=location,
        start=start,
        end=end,
        layers=SMAP_SOIL_MOISTURE_LAYERS,
    )
    register_job(
        JobRegistryEntry(
            task_id=task_id,
            source="appeears_smap",
            location=location,
            layers=SMAP_SOIL_MOISTURE_LAYERS,
        )
    )
    return {"job_id": task_id, "source": "appeears_smap", "status": "queued"}
