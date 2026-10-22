from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, Response

from ....clients.open_meteo import (
    DEFAULT_FORECAST_VARIABLES,
    MAX_FORECAST_DAYS,
    OpenMeteoClient,
)
from ....clients.power import DEFAULT_PARAMETERS, PowerClient
from ....schemas.common import TimeSeries
from ....schemas.variables import CanonicalVariable
from ..deps import OutputFormat, common_query, format_response

router = APIRouter(prefix="/climate", tags=["climate"])


@router.get(
    "/history",
    summary="Daily historical climatology from NASA POWER",
    response_model=list[TimeSeries] | None,
    responses={
        200: {
            "description": "A list of TimeSeries (one per canonical variable).",
            "content": {
                "application/json": {"example": []},
                "text/csv": {},
                "application/octet-stream": {},
            },
        }
    },
)
async def climate_history(
    params: dict = Depends(common_query),
    variables: list[CanonicalVariable] | None = Query(
        default=None,
        description="Canonical variables to return. Defaults to the full agro bundle.",
    ),
) -> Response | list[TimeSeries]:
    fmt: OutputFormat = params["format"]
    client = PowerClient()
    series = await client.daily_point(
        location=params["location"],
        start=params["start"],
        end=params["end"],
        variables=variables or DEFAULT_PARAMETERS,
    )
    return format_response(series, fmt)


@router.get(
    "/forecast",
    summary="Short-term daily forecast from Open-Meteo (1-16 days)",
    response_model=list[TimeSeries] | None,
)
async def climate_forecast(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    start: date | None = Query(default=None, description="Optional start date."),
    end: date | None = Query(default=None, description="Optional end date."),
    forecast_days: int | None = Query(
        default=None,
        ge=1,
        le=MAX_FORECAST_DAYS,
        description="Number of forecast days (ignored when start/end are given).",
    ),
    variables: list[CanonicalVariable] | None = Query(default=None),
    format: OutputFormat = Query("json"),
) -> Response | list[TimeSeries]:
    from ....schemas.common import Location

    client = OpenMeteoClient()
    series = await client.forecast(
        location=Location(lat=lat, lon=lon),
        start=start,
        end=end,
        forecast_days=forecast_days,
        variables=variables or DEFAULT_FORECAST_VARIABLES,
    )
    return format_response(series, format)
