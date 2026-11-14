from fastapi import APIRouter

from .routers import (
    climate,
    crop_suitability,
    features,
    jobs,
    mobile_app,
    precipitation,
    projections,
    soil_moisture,
    terrain,
    vegetation,
    water_stress,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(climate.router)
api_router.include_router(precipitation.router)
api_router.include_router(vegetation.router)
api_router.include_router(soil_moisture.router)
api_router.include_router(water_stress.router)
api_router.include_router(terrain.router)
api_router.include_router(jobs.router)
api_router.include_router(projections.router)
api_router.include_router(crop_suitability.router)
api_router.include_router(features.router)
api_router.include_router(mobile_app.router)

__all__ = ["api_router"]
