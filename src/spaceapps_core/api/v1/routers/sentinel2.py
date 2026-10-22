from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query

from ....clients.copernicus import CopernicusClient
from ....schemas.common import Location

router = APIRouter(prefix="/sentinel-2", tags=["sentinel-2"])


@router.get(
    "/scenes",
    summary="Search Sentinel-2 scenes on Copernicus Data Space STAC",
    response_model=list[dict],
)
async def search_scenes(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    start: date = Query(...),
    end: date = Query(...),
    max_cloud_cover: float | None = Query(
        default=50.0, ge=0, le=100, description="Maximum eo:cloud_cover (percent)."
    ),
    limit: int = Query(default=20, ge=1, le=200),
) -> list[dict]:
    client = CopernicusClient()
    return await client.search_sentinel2(
        location=Location(lat=lat, lon=lon),
        start=start,
        end=end,
        max_cloud_cover=max_cloud_cover,
        limit=limit,
    )
