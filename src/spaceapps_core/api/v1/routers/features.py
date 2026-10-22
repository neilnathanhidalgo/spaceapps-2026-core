from __future__ import annotations

import io
from datetime import date

from fastapi import APIRouter, Query, Response

from ....schemas.common import Location
from ....schemas.variables import CanonicalVariable
from ....services.features import build_features
from ..deps import OutputFormat

router = APIRouter(prefix="/features", tags=["features"])


@router.get(
    "",
    summary="Merged daily feature table (POWER + optional Open-Meteo + IMERG)",
    response_model=None,
)
async def features(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    start: date = Query(...),
    end: date = Query(...),
    variables: list[CanonicalVariable] | None = Query(default=None),
    include_forecast: bool = Query(default=False),
    include_imerg: bool = Query(default=False),
    format: OutputFormat = Query("json"),
) -> Response | list[dict]:
    df = await build_features(
        location=Location(lat=lat, lon=lon),
        start=start,
        end=end,
        variables=variables,
        include_forecast=include_forecast,
        include_imerg=include_imerg,
    )

    df_out = df.copy()
    if "date" in df_out.columns:
        df_out["date"] = df_out["date"].astype(str)

    if format == "json":
        return df_out.to_dict(orient="records")

    if format == "csv":
        return Response(content=df_out.to_csv(index=False), media_type="text/csv")

    buf = io.BytesIO()
    df_out.to_parquet(buf, index=False)
    return Response(content=buf.getvalue(), media_type="application/octet-stream")
