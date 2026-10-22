from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from ....clients.earthdata import EarthdataClient
from ....schemas.common import TimeSeries
from ..deps import OutputFormat, common_query, format_response

router = APIRouter(prefix="/precipitation", tags=["precipitation"])


@router.get(
    "",
    summary="Daily IMERG precipitation (GPM_3IMERGDF) at a point",
    response_model=TimeSeries | None,
)
async def precipitation(
    params: dict = Depends(common_query),
) -> Response | TimeSeries:
    fmt: OutputFormat = params["format"]
    client = EarthdataClient()
    series = await client.imerg_daily_point(
        location=params["location"],
        start=params["start"],
        end=params["end"],
    )
    return format_response(series, fmt)
