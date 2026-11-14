from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .common import Location

GaezInputLevel = Literal["high", "low"]


class CropSuitability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    crop: str
    suitability_index: float | None = Field(
        ...,
        ge=0,
        le=1,
        description="0 = not suitable, 1 = optimal. Null when GAEZ has no data for the cell.",
    )


class CropSuitabilityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location: Location
    period: str
    water_supply: Literal["rainfed"] = "rainfed"
    input_level: GaezInputLevel
    crops: list[CropSuitability] = Field(description="Sorted from most to least suitable.")
    source: str = "fao_gaez"
    retrieved_at: datetime = Field(default_factory=datetime.utcnow)
