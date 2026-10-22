from fastapi import APIRouter

from .routers import (
    climate,
    features,
    jobs,
    precipitation,
    projections,
    sentinel2,
    soil_moisture,
    vegetation,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(climate.router)
api_router.include_router(precipitation.router)
api_router.include_router(vegetation.router)
api_router.include_router(soil_moisture.router)
api_router.include_router(jobs.router)
api_router.include_router(projections.router)
api_router.include_router(sentinel2.router)
api_router.include_router(features.router)

__all__ = ["api_router"]
