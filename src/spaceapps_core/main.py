from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .api.v1 import api_router
from .api.v1.routers.health import router as health_router
from .core.config import get_settings
from .core.errors import register_exception_handlers
from .core.logging import configure_logging, get_logger


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    log = get_logger("startup")
    settings = get_settings()
    log.info(
        "app_start",
        app=settings.app_name,
        env=settings.app_env,
        earthdata_configured=settings.earthdata_configured,
        copernicus_configured=settings.copernicus_configured,
    )
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="spaceapps-2026-core",
        version=__version__,
        description=(
            "Backend for NASA Space Apps 2026 - Field Shift. "
            "Unified access to NASA POWER, Open-Meteo, AppEEARS (MODIS/VIIRS/SMAP), "
            "GPM IMERG, NEX-GDDP-CMIP6 and Copernicus Sentinel-2."
        ),
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    app.include_router(health_router)
    app.include_router(api_router)

    return app


app = create_app()
