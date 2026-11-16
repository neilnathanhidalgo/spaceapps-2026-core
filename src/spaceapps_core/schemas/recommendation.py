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
SoilTexture = Literal["sandy", "loamy", "clayey"]
VegetationDirection = Literal["down", "flat", "up"]
RankingCriterion = Literal["least_water", "most_soil_improvement", "least_climate_risk"]
SoilTextureSource = Literal["farmer", "soilgrids"]
SoilMoistureBand = Literal["dry", "normal", "wet"]
CropWaterNeed = Literal["low", "medium", "high"]

SCENARIO_IDS: tuple[ScenarioId, ...] = ("heavy_rains", "normal", "dry")

CUSTOM_ROTATION_ID = "custom"
"""Id of the option the farmer builds; reserved, no config rotation may use it."""


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
    custom_rotation: list[str] | None = Field(
        default=None,
        description=(
            "Crop ids the farmer put together, in planting order. Comes back as an "
            f'extra option with id "{CUSTOM_ROTATION_ID}".'
        ),
    )
    reported_soil_texture: SoilTexture | None = Field(
        default=None,
        description=(
            "Texture the farmer recognized in their own plot. Wins over SoilGrids: "
            "they know the field, SoilGrids averages 250 m."
        ),
    )


class CatalogCrop(_Strict):
    id: str
    name: str
    cycle_months: int = Field(..., description="Length of `kc_by_month`.")
    soil_impact: SoilImpactKind
    water_need: CropWaterNeed = Field(
        ..., description="Band of `water_index` against the catalog thresholds."
    )
    water_index: float = Field(
        ...,
        description="Sum of the cycle's Kc: how many months of full ET0 the crop asks for.",
    )
    fixes_nitrogen: bool = Field(
        ..., description="Whether the crop leaves nitrogen behind for the next one."
    )


class CatalogPriority(_Strict):
    id: str
    name: str
    phrase: str = Field(..., description="Short form to drop into a sentence.")


class CatalogRestriction(_Strict):
    id: str
    name: str


class CatalogSoilTexture(_Strict):
    """One answer to "does your soil look like this one?"."""

    id: SoilTexture
    name: str
    description: str = Field(..., description="How the farmer recognizes it in their hand.")


class AppCatalog(_Strict):
    """Crops, priorities and restrictions the app offers to the farmer."""

    crops: list[CatalogCrop]
    priorities: list[CatalogPriority] = Field(
        ..., description="In display order; the first one is the suggested default."
    )
    restrictions: list[CatalogRestriction]
    soil_textures: list[CatalogSoilTexture] = Field(
        ..., description="Answers to `soil_texture_question`; empty hides the question."
    )
    soil_texture_question: str
    max_rotation_crops: int = Field(
        ..., description="How many crops the farmer can chain in `custom_rotation`."
    )
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
    warnings: list[str] = Field(
        default_factory=list,
        description=(
            "Agronomic rules the sequence breaks (same family in a row, planting "
            "outside the usual months), in the farmer's words. Each one raises the "
            "risk to at least medium."
        ),
    )


class CurrentPracticeOut(_Strict):
    """Repeating the last crop, as the comparison baseline."""

    crop_ids: list[str]
    consecutive_campaigns: int
    cycle_months: int
    soil_in_two_years: SoilConditionLevel
    factsheet: OptionFactsheet
    repeat_warnings: dict[ScenarioId, str]
    scenarios: dict[ScenarioId, ScenarioResult]
    warnings: list[str] = Field(
        default_factory=list, description="Same as `RotationOptionOut.warnings`."
    )


class SoilProfile(_Strict):
    """What SoilGrids says about the soil under the plot."""

    sand_percent: float
    clay_percent: float
    organic_carbon_g_kg: float
    texture: SoilTexture
    depth: str = Field(..., description="Depth interval of the sample, e.g. 0-5cm.")
    source: str = "soilgrids"


class VegetationTrend(_Strict):
    """How the plot's greenness (NDVI) moved between two years."""

    start_year: int
    end_year: int
    start_ndvi: float
    end_ndvi: float
    change_ratio: float = Field(..., description="Relative change; -0.18 means greenness fell 18%.")
    direction: VegetationDirection
    source: str = "ornl_modis"


class SoilMoistureState(_Strict):
    """How wet the top of the soil has been, measured by SMAP."""

    mean_m3_m3: float = Field(..., description="Mean volumetric water content of the window.")
    band: SoilMoistureBand
    start: date
    end: date
    observed_days: int
    source: str = "smap"


class SoilHealth(_Strict):
    condition: SoilConditionLevel
    findings: list[str]
    texture: SoilTexture | None = Field(
        default=None, description="Texture the water balance used. Null when nobody knows it."
    )
    texture_source: SoilTextureSource | None = Field(
        default=None, description="Who said so. Null when `texture` is null."
    )
    profile: SoilProfile | None = Field(
        default=None, description="Null when SoilGrids has no data for the point."
    )
    vegetation_trend: VegetationTrend | None = Field(
        default=None, description="Null when there is not enough NDVI history."
    )
    soil_moisture: SoilMoistureState | None = Field(
        default=None, description="Null until the SMAP window of the point is warm."
    )


class MonthClimate(_Strict):
    """Scenario climate of one month of the year, averaged over the reference years."""

    month: int = Field(..., ge=1, le=12)
    rain_mm: float
    t2m_max: float
    t2m_min: float
    et0_mm_day: float
    is_risk_month: bool


class RecentRain(_Strict):
    """Rain already measured over the plot, and the scenario it looks like.

    GPM IMERG sees 0.1 degrees against POWER's 0.5, so it is the finer look at
    what the current campaign actually got.
    """

    start: date
    end: date
    observed_days: int
    total_mm: float
    scenario_totals: dict[ScenarioId, float] = Field(
        ...,
        description="What the same days of the year add up to in each scenario's reference years.",
    )
    closest_scenario: ScenarioId = Field(
        ..., description="Scenario whose expected total is nearest to `total_mm`."
    )
    finding: str = Field(..., description="The same thing in the farmer's words.")
    source: str = "gpm_imerg"


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
    crops: list[CatalogCrop] = Field(
        ...,
        description="Crops referenced by `crop_ids`, so the response needs no catalog call.",
    )
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
    recent_rain: RecentRain | None = Field(
        default=None, description="Null until the IMERG window of the point is warm."
    )
    risk_months: dict[ScenarioId, list[date]]
    scenario_notes: dict[ScenarioId, str]
    irrigation_source: str
    climate_basis: ClimateBasis
    data_sources: list[str] = Field(..., description="Upstreams that actually fed this response.")
    example_parameters: bool
    generated_at: datetime
