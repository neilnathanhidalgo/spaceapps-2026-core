from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Query

from ....schemas.climate_overview import ClimateOverview
from ....schemas.common import Location
from ....schemas.recommendation import (
    AppCatalog,
    RecommendationRequest,
    RecommendationResponse,
)
from ....services.app_catalog import build_catalog
from ....services.climate_overview import build_climate_overview
from ....services.recent_rain import warm_recent_rain
from ....services.recommendation import recommend
from ....services.soil_moisture import warm_soil_moisture
from ....services.vegetation import warm_vegetation_trend

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


@router.get(
    "/catalog",
    summary="Crops, priorities and restrictions the app offers to the farmer",
    response_model=AppCatalog,
)
async def catalog() -> AppCatalog:
    return build_catalog()


@router.post(
    "/recommendation",
    summary="Rotation recommendation for the three scenarios, from NASA POWER",
    response_model=RecommendationResponse,
)
async def recommendation(
    request: RecommendationRequest,
    background: BackgroundTasks,
) -> RecommendationResponse:
    response = await recommend(request)
    # Lo que tarda minutos (NDVI, SMAP, IMERG) no se espera: se deja pedido
    # para la próxima vez que alguien pregunte por este punto.
    if response.soil_health.vegetation_trend is None:
        background.add_task(warm_vegetation_trend, response.location)
    if response.soil_health.soil_moisture is None:
        background.add_task(warm_soil_moisture, response.location)
    if response.recent_rain is None:
        background.add_task(warm_recent_rain, response.location)
    return response
