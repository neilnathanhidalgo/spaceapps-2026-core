from __future__ import annotations

import io
from datetime import date
from typing import Literal

from fastapi import HTTPException, Query, Response

from ...core.config import Settings, get_settings
from ...schemas.common import Location, TimeSeries

OutputFormat = Literal["json", "csv", "parquet"]


def common_query(
    lat: float = Query(..., ge=-90, le=90, description="Latitude in decimal degrees."),
    lon: float = Query(..., ge=-180, le=180, description="Longitude in decimal degrees."),
    start: date = Query(..., description="Inclusive start date (YYYY-MM-DD)."),
    end: date = Query(..., description="Inclusive end date (YYYY-MM-DD)."),
    format: OutputFormat = Query("json", description="Response format."),
) -> dict:
    if end < start:
        raise HTTPException(
            status_code=400,
            detail="`end` must be greater than or equal to `start`.",
        )
    return {
        "location": Location(lat=lat, lon=lon),
        "start": start,
        "end": end,
        "format": format,
    }


def settings_dep() -> Settings:
    return get_settings()


def format_response(
    series: TimeSeries | list[TimeSeries],
    fmt: OutputFormat,
) -> Response | TimeSeries | list[TimeSeries]:
    if fmt == "json":
        return series

    from ...clients.base import BaseClient

    df = BaseClient.to_dataframe(series)

    if fmt == "csv":
        return Response(content=df.to_csv(index=False), media_type="text/csv")

    if fmt == "parquet":
        buf = io.BytesIO()
        df.to_parquet(buf, index=False)
        return Response(content=buf.getvalue(), media_type="application/octet-stream")

    raise HTTPException(status_code=400, detail=f"Unsupported format: {fmt}")
