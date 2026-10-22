from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query, Response

from ....clients.nex_gddp import (
    DEFAULT_MODEL,
    DEFAULT_VARIABLES,
    SUPPORTED_SCENARIOS,
    NexGddpClient,
)
from ....schemas.common import Location, TimeSeries
from ....schemas.variables import CanonicalVariable
from ..deps import OutputFormat, format_response

router = APIRouter(prefix="/projections", tags=["projections"])


@router.get(
    "",
    summary="Daily climate projections (NEX-GDDP-CMIP6) at a point",
    response_model=list[TimeSeries] | None,
)
async def projections(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    start: date = Query(..., description="Inclusive start date (YYYY-MM-DD)."),
    end: date = Query(..., description="Inclusive end date (YYYY-MM-DD)."),
    scenario: str = Query("ssp245", description=f"One of: {sorted(SUPPORTED_SCENARIOS)}"),
    model: str = Query(DEFAULT_MODEL, description="CMIP6 model identifier."),
    variables: list[CanonicalVariable] | None = Query(default=None),
    format: OutputFormat = Query("json"),
) -> Response | list[TimeSeries]:
    client = NexGddpClient(model=model)
    series = await client.projections_point(
        location=Location(lat=lat, lon=lon),
        start=start,
        end=end,
        scenario=scenario,
        variables=variables or DEFAULT_VARIABLES,
    )
    return format_response(series, format)
