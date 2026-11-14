"""Request and response models for the mobile app's planting recommendation."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .common import Location

ScenarioId = Literal["heavy_rains", "normal", "dry"]
SoilImpactKind = Literal["degrades", "neutral", "improves", "improves_a_lot"]
SoilConditionLevel = Literal["very_tired", "tired", "regular", "good"]
ClimateRiskLevel = Literal["low", "medium", "high"]
RankingCriterion = Literal["least_water", "most_soil_improvement", "least_climate_risk"]

SCENARIO_IDS: tuple[ScenarioId, ...] = ("heavy_rains", "normal", "dry")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RecommendationRequest(_Strict):
    """What the farmer enters, plus the plot location."""

    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    area_ha: float = Field(default=1.0, gt=0, le=10_000, description="Plot area in hectares.")
    planting_date: date = Field(..., description="When the first crop of the rotation goes in.")
    last_crop_id: str | None = Field(
        default=None,
        description="Crop of the last campaign. Null uses `defaults.last_crop_id`.",
    )
    consecutive_campaigns: int = Field(
        default=1,
        ge=0,
        le=50,
        description="How many campaigns in a row the plot has grown `last_crop_id`.",
    )
    priority_id: str | None = Field(
        default=None,
        description="Chosen priority. Null uses the first priority of the catalog.",
    )
    restriction_ids: list[str] = Field(default_factory=list)


class CatalogCrop(_Strict):
    id: str
    name: str
    cycle_months: int = Field(..., description="Length of `kc_by_month`.")
    soil_impact: SoilImpactKind


class CatalogPriority(_Strict):
    id: str
    name: str
    phrase: str = Field(..., description="Short form to drop into a sentence.")


class CatalogRestriction(_Strict):
    id: str
    name: str


class AppCatalog(_Strict):
    """Crops, priorities and restrictions the app offers to the farmer."""

    crops: list[CatalogCrop]
    priorities: list[CatalogPriority] = Field(
        ..., description="In display order; the first one is the suggested default."
    )
    restrictions: list[CatalogRestriction]
    example_parameters: bool = Field(
        ..., description="True while any block of `agro_config.json` is marked `_example`."
    )


class MonthWater(_Strict):
    """Irrigation balance of one calendar month of a crop cycle."""

    month: date = Field(..., description="First day of the calendar month.")
    crop_id: str
    kc: float
    et0_mm_day: float
    rain_mm: float
    effective_rain_mm: float
    irrigation_mm: float
    irrigation_m3: float


class CropPeriod(_Strict):
    crop_id: str
    start: date = Field(..., description="First day of the first calendar month of the crop.")
    month_count: int


class RotationCalendar(_Strict):
    planting_date: date
    decision_deadline: date
    timeline_start: date
    timeline_months: int
    periods: list[CropPeriod]
    instructions: str


class CampaignStep(_Strict):
    """One campaign of the long-term plan and how the soil ends up after it."""

    crop_id: str
    start: date
    end: date
    soil_after: SoilConditionLevel


class ScenarioResult(_Strict):
    """Water and climate risk of one option under one scenario."""

    irrigation_m3: float
    irrigation_m3_per_ha: float
    risk_months: list[date]
    risk_month_count: int
    climate_risk: ClimateRiskLevel
    monthly: list[MonthWater]


class OptionFactsheet(_Strict):
    rationale: str
    evidence: str
    benefits: str
    unknowns: str
    risks: str


class RotationOptionOut(_Strict):
    id: str
    crop_ids: list[str]
    cycle_months: int
    soil_impact: SoilImpactKind
    soil_impact_score: int
    soil_in_two_years: SoilConditionLevel
    factsheet: OptionFactsheet
    excluded_by: list[str] = Field(
        ..., description="Restriction ids that rule this option out for this farmer."
    )
    calendar: RotationCalendar
    long_term_plan: list[CampaignStep]
    scenarios: dict[ScenarioId, ScenarioResult]


class CurrentPracticeOut(_Strict):
    """Repeating the last crop, as the comparison baseline."""

    crop_ids: list[str]
    consecutive_campaigns: int
    cycle_months: int
    soil_in_two_years: SoilConditionLevel
    factsheet: OptionFactsheet
    repeat_warnings: dict[ScenarioId, str]
    scenarios: dict[ScenarioId, ScenarioResult]


class SoilHealth(_Strict):
    condition: SoilConditionLevel
    findings: list[str]


class MonthClimate(_Strict):
    """Scenario climate of one month of the year, averaged over the reference years."""

    month: int = Field(..., ge=1, le=12)
    rain_mm: float
    t2m_max: float
    t2m_min: float
    et0_mm_day: float
    is_risk_month: bool


class ClimateBasis(_Strict):
    source: str
    variables: list[str]
    reference_years: dict[ScenarioId, list[int]]
    et0_method: str
    effective_rain_fraction: float
    risk_month_rain_mm: float
    monthly_climate: dict[ScenarioId, list[MonthClimate]]


class RecommendationResponse(_Strict):
    """Everything the app needs for the three scenarios at once."""

    location: Location
    area_ha: float
    planting_date: date
    priority_id: str
    restriction_ids: list[str]
    options: list[RotationOptionOut]
    ranking: dict[str, dict[ScenarioId, list[str]]] = Field(
        ...,
        description=(
            "Option ids best first, per priority id and scenario; excluded ones included. "
            "Every priority of the catalog is there so the app can switch priority or "
            "scenario without asking again."
        ),
    )
    current_practice: CurrentPracticeOut
    soil_health: SoilHealth
    risk_months: dict[ScenarioId, list[date]]
    scenario_notes: dict[ScenarioId, str]
    irrigation_source: str
    climate_basis: ClimateBasis
    example_parameters: bool
    generated_at: datetime
