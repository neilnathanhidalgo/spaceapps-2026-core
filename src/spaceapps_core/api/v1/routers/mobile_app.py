from __future__ import annotations

from fastapi import APIRouter, Query

from ....schemas.climate_overview import ClimateOverview
from ....schemas.common import Location
from ....services.climate_overview import build_climate_overview

router = APIRouter(prefix="/app", tags=["app"])


@router.get(
    "/climate-overview",
    summary="Ready-to-render climate summary for the mobile app's Clima screen",
    response_model=ClimateOverview,
)
async def climate_overview(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
) -> ClimateOverview:
    return await build_climate_overview(Location(lat=lat, lon=lon))
