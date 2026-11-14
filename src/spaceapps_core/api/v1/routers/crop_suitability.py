from __future__ import annotations

from fastapi import APIRouter, Query

from ....clients.gaez import DEFAULT_CROPS, GaezClient
from ....schemas.common import Location
from ....schemas.crop_suitability import CropSuitabilityReport, GaezInputLevel

router = APIRouter(prefix="/crop-suitability", tags=["crop-suitability"])


@router.get(
    "",
    summary="Rainfed crop suitability from FAO GAEZ v4 (1981-2010 baseline)",
    response_model=CropSuitabilityReport,
)
async def crop_suitability(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    input_level: GaezInputLevel = Query(
        "high",
        description="`high`: mechanized, fertilized farming. `low`: traditional, low-input.",
    ),
    crops: list[str] | None = Query(
        default=None,
        description=f"GAEZ crop names. Defaults to: {', '.join(DEFAULT_CROPS)}.",
    ),
) -> CropSuitabilityReport:
    return await GaezClient().crop_suitability(
        Location(lat=lat, lon=lon),
        input_level=input_level,
        crops=crops,
    )
