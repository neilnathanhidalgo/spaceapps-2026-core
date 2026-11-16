"""Planting recommendation for the mobile app.

Pure functions plus one thin async wrapper that gets the scenario climate
from NASA POWER. Everything that computes can be imported and called from a
notebook: `build_recommendation` only needs the request, the parameters and
the monthly climate of each scenario.

How a scenario becomes numbers:

1. Monthly rainfall and temperatures of the scenario's reference years
   (NASA POWER daily), averaged across those years.
2. Monthly ET0 from `reference_et0` (Hargreaves) with the plot's latitude.
3. A calendar: the first crop starts on the farmer's planting date and each
   next crop starts when the previous one ends.
4. Irrigation per month: `max(0, ET0 x Kc x days - effective rainfall)`.
5. Risk months: months of the calendar whose scenario rainfall is above the
   threshold.

What the plot itself reports (SoilGrids, the farmer's own answer, MODIS NDVI,
SMAP and IMERG) is all fail-soft: every one of them can be missing and the
recommendation still comes out, saying so in `data_sources`.
"""

from __future__ import annotations

import asyncio
from calendar import monthrange
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from itertools import pairwise

from ..clients.power import PowerClient
from ..core.errors import InvalidRequestError, UpstreamError
from ..schemas.common import Location, TimeSeries
from ..schemas.recommendation import (
    CUSTOM_ROTATION_ID,
    SCENARIO_IDS,
    CampaignStep,
    ClimateBasis,
    ClimateRiskLevel,
    CropPeriod,
    CurrentPracticeOut,
    IrrigationWater,
    MonthClimate,
    MonthWater,
    OptionFactsheet,
    RankingCriterion,
    RecommendationRequest,
    RecommendationResponse,
    RotationCalendar,
    RotationOptionOut,
    ScenarioId,
    ScenarioResult,
    SoilConditionLevel,
    SoilHealth,
    SoilImpactKind,
    SoilMoistureState,
    SoilProfile,
    SoilTexture,
    SoilTextureSource,
    VegetationTrend,
    WaterAvailability,
)
from ..schemas.variables import CanonicalVariable
from .agro_config import (
    AgroConfig,
    ContentConfig,
    CropConfig,
    PriorityConfig,
    RestrictionConfig,
    ScenariosConfig,
    ThresholdsConfig,
    fill_template,
    load_agro_config,
)
from .app_catalog import catalog_crop, crop_water_need
from .et0 import reference_et0
from .irrigation_water import fetch_irrigation_water
from .local_soil import (
    carbon_score_shift,
    effective_rain_fraction,
    effective_texture,
    fetch_soil_profile,
)
from .observations import add_months
from .recent_rain import (
    RECENT_RAIN_SOURCE,
    ObservedRain,
    build_recent_rain,
    cached_recent_rain,
)
from .soil_moisture import cached_soil_moisture
from .vegetation import cached_vegetation_trend
from .water_availability import fetch_water_availability

CLIMATE_VARIABLES = [
    CanonicalVariable.PRECIPITATION,
    CanonicalVariable.T2M_MAX,
    CanonicalVariable.T2M_MIN,
]
MM_PER_HA_TO_M3 = 10.0
MID_MONTH_DAY = 15
SOIL_CONDITIONS: tuple[SoilConditionLevel, ...] = ("very_tired", "tired", "regular", "good")
FACTSHEET_SECTIONS = ("rationale", "evidence", "benefits", "unknowns", "risks")
MONTH_NAMES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "setiembre",
    "octubre",
    "noviembre",
    "diciembre",
)
RISK_ORDER: tuple[ClimateRiskLevel, ...] = ("low", "medium", "high")


@dataclass(frozen=True)
class MonthlyWeather:
    """Scenario weather of one month of the year."""

    rain_mm: float
    t2m_max: float
    t2m_min: float


ScenarioClimate = dict[int, MonthlyWeather]
"""Monthly weather of a scenario, keyed by month of the year (1-12)."""


@dataclass(frozen=True)
class CropWindow:
    """Calendar months a crop occupies the field."""

    crop: CropConfig
    start: date

    @property
    def month_count(self) -> int:
        return self.crop.cycle_months

    @property
    def months(self) -> list[date]:
        return [add_months(self.start, offset) for offset in range(self.month_count)]


@dataclass(frozen=True)
class RankingInput:
    """What the priorities compare, per option and scenario."""

    option_id: str
    irrigation_m3: float
    risk_month_count: int
    soil_impact_score: int
    has_high_water_crop: bool = False
    worst_risk_month_count: int = 0
    rule_warning_count: int = 0


def average_monthly_weather(series: Iterable[TimeSeries], years: Sequence[int]) -> ScenarioClimate:
    """Average the daily POWER series of [years] into one value per month.

    Rainfall is the mean of the monthly totals; temperatures are the mean of
    the daily values. Missing days are skipped.
    """
    wanted = set(years)
    rain: dict[int, dict[int, float]] = {}
    highs: dict[int, list[float]] = {}
    lows: dict[int, list[float]] = {}
    for one in series:
        for point in one.points:
            if point.value is None or point.date.year not in wanted:
                continue
            month = point.date.month
            if one.variable is CanonicalVariable.PRECIPITATION:
                by_year = rain.setdefault(month, {})
                by_year[point.date.year] = by_year.get(point.date.year, 0.0) + point.value
            elif one.variable is CanonicalVariable.T2M_MAX:
                highs.setdefault(month, []).append(point.value)
            elif one.variable is CanonicalVariable.T2M_MIN:
                lows.setdefault(month, []).append(point.value)

    climate: ScenarioClimate = {}
    for month in range(1, 13):
        totals, high, low = rain.get(month), highs.get(month), lows.get(month)
        if not totals or not high or not low:
            raise UpstreamError(
                f"NASA POWER has no complete data for month {month} of {sorted(wanted)}.",
                details={"month": month, "years": sorted(wanted)},
            )
        climate[month] = MonthlyWeather(
            rain_mm=_mean(list(totals.values())),
            t2m_max=_mean(high),
            t2m_min=_mean(low),
        )
    return climate


def monthly_et0(climate: ScenarioClimate, latitude: float) -> dict[int, float]:
    """ET0 in mm/day of each month of the year, computed at mid-month."""
    return {
        month: reference_et0(
            t2m_max=weather.t2m_max,
            t2m_min=weather.t2m_min,
            latitude=latitude,
            day_of_year=_mid_month_day_of_year(month),
        )
        for month, weather in climate.items()
    }


def risky_months_of_year(climate: ScenarioClimate, rain_threshold_mm: float) -> set[int]:
    """Months of the year whose scenario rainfall is above the threshold."""
    return {month for month, weather in climate.items() if weather.rain_mm > rain_threshold_mm}


def crop_windows(planting_date: date, crops: Sequence[CropConfig]) -> list[CropWindow]:
    """Calendar of the rotation: each crop starts when the previous one ends."""
    windows: list[CropWindow] = []
    start = date(planting_date.year, planting_date.month, 1)
    for crop in crops:
        windows.append(CropWindow(crop=crop, start=start))
        start = add_months(start, crop.cycle_months)
    return windows


def repeated_crops(crops: Sequence[CropConfig], horizon_months: int) -> list[CropConfig]:
    """The rotation repeated until the horizon is covered."""
    repeated: list[CropConfig] = []
    used = 0
    while used < horizon_months:
        crop = crops[len(repeated) % len(crops)]
        repeated.append(crop)
        used += crop.cycle_months
    return repeated


def month_waters(
    windows: Sequence[CropWindow],
    climate: ScenarioClimate,
    et0_by_month: dict[int, float],
    *,
    area_ha: float,
    effective_rain_fraction: float,
) -> list[MonthWater]:
    """Irrigation balance of every calendar month of the rotation."""
    waters: list[MonthWater] = []
    for window in windows:
        for index, month_start in enumerate(window.months):
            weather = climate[month_start.month]
            et0 = et0_by_month[month_start.month]
            kc = window.crop.kc_by_month[index]
            days = monthrange(month_start.year, month_start.month)[1]
            effective_rain = weather.rain_mm * effective_rain_fraction
            irrigation_mm = max(et0 * kc * days - effective_rain, 0.0)
            waters.append(
                MonthWater(
                    month=month_start,
                    crop_id=window.crop.id,
                    kc=round(kc, 2),
                    et0_mm_day=round(et0, 2),
                    rain_mm=round(weather.rain_mm, 1),
                    effective_rain_mm=round(effective_rain, 1),
                    irrigation_mm=round(irrigation_mm, 1),
                    irrigation_m3=round(irrigation_mm * area_ha * MM_PER_HA_TO_M3, 1),
                )
            )
    return waters


def calendar_risk_months(windows: Sequence[CropWindow], risky: set[int]) -> list[date]:
    """Months of the rotation's calendar that fall on a risk month."""
    return [month for window in windows for month in window.months if month.month in risky]


def climate_risk_level(risk_month_count: int, thresholds: ThresholdsConfig) -> ClimateRiskLevel:
    """Risk level of an option from how many risk months its calendar hits."""
    if risk_month_count >= thresholds.climate_risk_high_months:
        return "high"
    if risk_month_count >= thresholds.climate_risk_medium_months:
        return "medium"
    return "low"


def scenario_result(
    windows: Sequence[CropWindow],
    climate: ScenarioClimate,
    et0_by_month: dict[int, float],
    risky: set[int],
    *,
    area_ha: float,
    thresholds: ThresholdsConfig,
    rain_fraction: float | None = None,
) -> ScenarioResult:
    """Water and climate risk of one rotation under one scenario."""
    waters = month_waters(
        windows,
        climate,
        et0_by_month,
        area_ha=area_ha,
        effective_rain_fraction=rain_fraction or thresholds.effective_rain_fraction,
    )
    risk_months = calendar_risk_months(windows, risky)
    irrigation_mm = sum(water.irrigation_mm for water in waters)
    return ScenarioResult(
        irrigation_m3=round(irrigation_mm * area_ha * MM_PER_HA_TO_M3, 1),
        irrigation_m3_per_ha=round(irrigation_mm * MM_PER_HA_TO_M3, 1),
        risk_months=risk_months,
        risk_month_count=len(risk_months),
        climate_risk=climate_risk_level(len(risk_months), thresholds),
        monthly=waters,
    )


def soil_condition(score: int) -> SoilConditionLevel:
    """Soil condition for a score, clamped to the 0-3 scale."""
    return SOIL_CONDITIONS[min(max(score, 0), len(SOIL_CONDITIONS) - 1)]


def current_soil_score(
    last_crop: CropConfig,
    consecutive_campaigns: int,
    thresholds: ThresholdsConfig,
    *,
    soil: SoilProfile | None = None,
    vegetation: VegetationTrend | None = None,
) -> int:
    """Soil score today.

    Starts from the baseline, moves it with the organic carbon SoilGrids
    reports, takes away points if the plot's greenness is falling (MODIS
    NDVI) and applies the last crop's impact once per campaign that counts.
    """
    campaigns = max(consecutive_campaigns - thresholds.soil_campaigns_before_penalty, 0)
    declining = vegetation is not None and vegetation.direction == "down"
    score = (
        thresholds.soil_baseline_score
        + carbon_score_shift(soil, thresholds)
        - (thresholds.soil_vegetation_decline_penalty if declining else 0)
        + last_crop.soil_score * campaigns
    )
    return min(max(score, 0), len(SOIL_CONDITIONS) - 1)


def long_term_plan(
    planting_date: date,
    crops: Sequence[CropConfig],
    start_score: int,
    horizon_months: int,
) -> list[CampaignStep]:
    """Campaigns within the horizon and how the soil ends up after each one."""
    steps: list[CampaignStep] = []
    score = start_score
    for window in crop_windows(planting_date, repeated_crops(crops, horizon_months)):
        score = min(max(score + window.crop.soil_score, 0), len(SOIL_CONDITIONS) - 1)
        steps.append(
            CampaignStep(
                crop_id=window.crop.id,
                start=window.start,
                end=add_months(window.start, window.month_count - 1),
                soil_after=soil_condition(score),
            )
        )
    return steps


def rule_warnings(
    planting_date: date,
    crops: Sequence[CropConfig],
    horizon_months: int,
    content: ContentConfig,
) -> list[str]:
    """Agronomic rules the rotation breaks within the horizon.

    1. Two crops of the same botanical family must not follow each other
       (the rotation repeats, so the last crop is followed by the first).
    2. Each crop must start in one of its usual planting months.
    """
    sequence = repeated_crops(crops, horizon_months)
    warnings: list[str] = []
    seen_pairs: set[frozenset[str]] = set()
    for first, second in pairwise(sequence):
        pair = frozenset((first.id, second.id))
        if first.family == second.family and pair not in seen_pairs:
            seen_pairs.add(pair)
            warnings.append(
                fill_template(
                    content.same_family_warning,
                    first=first.name,
                    second=second.name.lower(),
                    family=first.family,
                )
            )
    flagged: set[str] = set()
    for window in crop_windows(planting_date, sequence):
        # Una advertencia por cultivo: la primera vez que cae fuera de sus meses.
        if window.crop.id in flagged:
            continue
        if window.start.month not in window.crop.planting_months:
            flagged.add(window.crop.id)
            warnings.append(
                fill_template(
                    content.planting_month_warning,
                    crop=window.crop.name.lower(),
                    month=MONTH_NAMES[window.start.month - 1],
                    months=_month_list(window.crop.planting_months),
                )
            )
    return list(dict.fromkeys(warnings))


def with_rule_risk(
    results: dict[ScenarioId, ScenarioResult],
    warnings: Sequence[str],
) -> dict[ScenarioId, ScenarioResult]:
    """A sequence that breaks a rule is never "low" risk."""
    if not warnings:
        return results
    return {
        scenario: (
            result.model_copy(update={"climate_risk": "medium"})
            if RISK_ORDER.index(result.climate_risk) < RISK_ORDER.index("medium")
            else result
        )
        for scenario, result in results.items()
    }


def soil_impact_of(crops: Sequence[CropConfig]) -> tuple[SoilImpactKind, int]:
    """Combined soil impact of a rotation, and its score."""
    score = sum(crop.soil_score for crop in crops)
    if score < 0:
        return "degrades", score
    if score == 0:
        return "neutral", score
    if score == 1:
        return "improves", score
    return "improves_a_lot", score


def rank_options(
    inputs: Sequence[RankingInput],
    criterion: RankingCriterion,
    *,
    water_low: bool = False,
) -> list[str]:
    """Option ids from best to worst for a priority. Ties keep the input order.

    - Cuidar el agua: less irrigation; with little water available
      (`water_low`), options with a high-water crop go last.
    - Recuperar la tierra: more soil improvement, then fewer risk months.
    - Menos riesgo de clima: compared in the worst year (most risk months
      in any scenario), then in the scenario being viewed, then the
      agronomic rules the sequence breaks (planting out of season or the
      same family in a row are risks too), then soil improvement.

    Little water does not reorder the other two priorities: their options
    carry a warning instead (see `water_low_warning`).
    """
    keys = {
        "least_water": lambda option: (
            water_low and option.has_high_water_crop,
            option.irrigation_m3,
        ),
        "most_soil_improvement": lambda option: (
            -option.soil_impact_score,
            option.risk_month_count,
        ),
        "least_climate_risk": lambda option: (
            option.worst_risk_month_count,
            option.risk_month_count,
            option.rule_warning_count,
            -option.soil_impact_score,
            option.irrigation_m3,
        ),
    }
    return [option.option_id for option in sorted(inputs, key=keys[criterion])]


def water_low_warning(
    crops: Sequence[CropConfig],
    config: AgroConfig,
    water: WaterAvailability | None,
    irrigation: IrrigationWater | None,
) -> str | None:
    """Warning for a sequence with high-water crops when water is low."""
    reasons = [item.finding for item in (irrigation, water) if item and item.level == "low"]
    thirsty = list(
        dict.fromkeys(
            crop.name for crop in crops if crop_water_need(crop, config.thresholds) == "high"
        )
    )
    if not reasons or not thirsty:
        return None
    names = thirsty[0] if len(thirsty) == 1 else f"{', '.join(thirsty[:-1])} y {thirsty[-1]}"
    return fill_template(
        config.content.water_low_warning,
        crops=names,
        needs="pide" if len(thirsty) == 1 else "piden",
        reason=reasons[0],
    )


def factsheet_of(crops: Sequence[CropConfig]) -> OptionFactsheet:
    """One factsheet out of the texts of the crops, in planting order."""
    sections: dict[str, str] = {}
    for section in FACTSHEET_SECTIONS:
        seen: list[str] = []
        for crop in crops:
            text = getattr(crop, section)
            if text and text not in seen:
                seen.append(text)
        sections[section] = " ".join(seen)
    return OptionFactsheet(**sections)


def resolve_choices(
    config: AgroConfig,
    request: RecommendationRequest,
) -> tuple[PriorityConfig, list[RestrictionConfig], CropConfig]:
    """Match the farmer's ids against the catalog.

    Raises `InvalidRequestError` when one of them does not exist, so the
    request fails before spending a call on NASA POWER.
    """
    return (
        _priority_or_400(config, request.priority_id),
        _restrictions_or_400(config, request.restriction_ids),
        _crop_or_400(config, request.last_crop_id or config.defaults.last_crop_id),
    )


def build_recommendation(
    request: RecommendationRequest,
    config: AgroConfig,
    climates: dict[ScenarioId, ScenarioClimate],
    *,
    soil: SoilProfile | None = None,
    vegetation: VegetationTrend | None = None,
    soil_moisture: SoilMoistureState | None = None,
    recent_rain: ObservedRain | None = None,
    water: WaterAvailability | None = None,
    irrigation: IrrigationWater | None = None,
) -> RecommendationResponse:
    """Build the whole response. Pure: no network, no FastAPI.

    Every observation of the plot is optional: without them the engine falls
    back to the global rain fraction and to the baseline soil score.
    """

    priority, restrictions, last_crop = resolve_choices(config, request)
    custom_crops = _custom_rotation_or_400(config, request.custom_rotation)
    thresholds = config.thresholds
    location = Location(lat=request.lat, lon=request.lon)
    texture, texture_source = effective_texture(soil, request.reported_soil_texture)
    rain_fraction = effective_rain_fraction(texture, thresholds)

    et0 = {scenario: monthly_et0(climate, request.lat) for scenario, climate in climates.items()}
    risky = {
        scenario: risky_months_of_year(climate, thresholds.risk_month_rain_mm)
        for scenario, climate in climates.items()
    }

    def results(windows: Sequence[CropWindow]) -> dict[ScenarioId, ScenarioResult]:
        return {
            scenario: scenario_result(
                windows,
                climates[scenario],
                et0[scenario],
                risky[scenario],
                area_ha=request.area_ha,
                thresholds=thresholds,
                rain_fraction=rain_fraction,
            )
            for scenario in SCENARIO_IDS
        }

    soil_now = current_soil_score(
        last_crop,
        request.consecutive_campaigns,
        thresholds,
        soil=soil,
        vegetation=vegetation,
    )

    rotations: list[tuple[str, list[CropConfig]]] = [
        (rotation.id, [config.crop(crop_id) for crop_id in rotation.crop_ids])
        for rotation in config.rotations
    ]
    if custom_crops:
        rotations.append((CUSTOM_ROTATION_ID, custom_crops))

    options: list[RotationOptionOut] = []
    rule_counts: dict[str, int] = {}
    for rotation_id, crops in rotations:
        windows = crop_windows(request.planting_date, crops)
        impact, impact_score = soil_impact_of(crops)
        plan = long_term_plan(
            request.planting_date, crops, soil_now, thresholds.soil_horizon_months
        )
        warnings = rule_warnings(
            request.planting_date, crops, thresholds.soil_horizon_months, config.content
        )
        rule_counts[rotation_id] = len(warnings)
        water_warning = water_low_warning(crops, config, water, irrigation)
        by_scenario = with_rule_risk(
            results(windows), [*warnings, *([water_warning] if water_warning else [])]
        )
        options.append(
            RotationOptionOut(
                id=rotation_id,
                crop_ids=[crop.id for crop in crops],
                cycle_months=sum(window.month_count for window in windows),
                soil_impact=impact,
                soil_impact_score=impact_score,
                soil_in_two_years=plan[-1].soil_after if plan else soil_condition(soil_now),
                factsheet=factsheet_of(crops),
                excluded_by=_excluded_by(config, crops, by_scenario),
                calendar=_calendar(request.planting_date, windows, crops, thresholds),
                long_term_plan=plan,
                scenarios=by_scenario,
                warnings=[*warnings, *([water_warning] if water_warning else [])],
            )
        )

    baseline_crops = [last_crop] * config.defaults.current_practice_campaigns
    baseline_windows = crop_windows(request.planting_date, baseline_crops)
    baseline_plan = long_term_plan(
        request.planting_date, [last_crop], soil_now, thresholds.soil_horizon_months
    )
    baseline_warnings = rule_warnings(
        request.planting_date, [last_crop], thresholds.soil_horizon_months, config.content
    )
    if baseline_water := water_low_warning([last_crop], config, water, irrigation):
        baseline_warnings.append(baseline_water)
    current_practice = CurrentPracticeOut(
        crop_ids=[crop.id for crop in baseline_crops],
        consecutive_campaigns=request.consecutive_campaigns,
        cycle_months=sum(window.month_count for window in baseline_windows),
        soil_in_two_years=(
            baseline_plan[-1].soil_after if baseline_plan else soil_condition(soil_now)
        ),
        factsheet=factsheet_of([last_crop]),
        repeat_warnings=dict(config.content.repeat_warnings),
        scenarios=with_rule_risk(results(baseline_windows), baseline_warnings),
        warnings=baseline_warnings,
    )

    horizon = max([option.cycle_months for option in options] + [current_practice.cycle_months])

    return RecommendationResponse(
        location=location,
        area_ha=request.area_ha,
        planting_date=request.planting_date,
        priority_id=priority.id,
        restriction_ids=[restriction.id for restriction in restrictions],
        crops=[catalog_crop(crop, thresholds) for crop in config.crops],
        options=options,
        ranking={
            catalog_priority.id: {
                scenario: rank_options(
                    _ranking_inputs(options, scenario, config, rule_counts),
                    catalog_priority.criterion,
                    water_low=least_water_level(water, irrigation) == "low",
                )
                for scenario in SCENARIO_IDS
            }
            for catalog_priority in config.priorities
        },
        current_practice=current_practice,
        soil_health=SoilHealth(
            condition=soil_condition(soil_now),
            findings=_soil_findings(
                config,
                request,
                last_crop,
                soil,
                vegetation,
                soil_moisture,
                texture,
                texture_source,
            ),
            texture=texture,
            texture_source=texture_source,
            profile=soil,
            vegetation_trend=vegetation,
            soil_moisture=soil_moisture,
        ),
        recent_rain=(
            None
            if recent_rain is None
            else build_recent_rain(recent_rain, _monthly_rain(climates), config.content)
        ),
        risk_months={
            scenario: _horizon_risk_months(request.planting_date, horizon, risky[scenario])
            for scenario in SCENARIO_IDS
        },
        scenario_notes=dict(config.content.scenario_notes),
        irrigation_source=config.content.irrigation_source,
        climate_basis=ClimateBasis(
            source="nasa_power",
            variables=["PRECTOTCORR", "T2M_MAX", "T2M_MIN"],
            reference_years={
                scenario: config.scenarios.years_for(scenario) for scenario in SCENARIO_IDS
            },
            et0_method="hargreaves",
            effective_rain_fraction=rain_fraction,
            risk_month_rain_mm=thresholds.risk_month_rain_mm,
            monthly_climate={
                scenario: [
                    MonthClimate(
                        month=month,
                        rain_mm=round(weather.rain_mm, 1),
                        t2m_max=round(weather.t2m_max, 1),
                        t2m_min=round(weather.t2m_min, 1),
                        et0_mm_day=round(et0[scenario][month], 2),
                        is_risk_month=month in risky[scenario],
                    )
                    for month, weather in sorted(climates[scenario].items())
                ]
                for scenario in SCENARIO_IDS
            },
        ),
        water_availability=water,
        irrigation_water=irrigation,
        data_sources=_data_sources(soil, vegetation, soil_moisture, recent_rain, texture_source),
        example_parameters=config.example_parameters,
        generated_at=datetime.utcnow(),
    )


async def recommend(request: RecommendationRequest) -> RecommendationResponse:
    """Fetch every upstream in parallel and build the response.

    Only NASA POWER is required: SoilGrids and what the plot reports are
    fail-soft, so a farmer on a masked pixel still gets a recommendation.
    The NDVI trend, the SMAP moisture and the IMERG rain come from the cache,
    never from a live call: all three take minutes.
    """
    config = load_agro_config()
    resolve_choices(config, request)
    _custom_rotation_or_400(config, request.custom_rotation)
    location = Location(lat=request.lat, lon=request.lon)

    climates, soil, water, irrigation = await asyncio.gather(
        fetch_scenario_climates(location, config.scenarios),
        fetch_soil_profile(location, config.thresholds),
        _water_or_none(location),
        _irrigation_or_none(),
    )
    thresholds = config.thresholds
    # Lo que tarda minutos no se espera: se usa lo que ya está en caché y el
    # router lo refresca después de responder.
    vegetation = cached_vegetation_trend(
        location,
        years=thresholds.vegetation_trend_years,
        flat_tolerance=thresholds.vegetation_flat_tolerance,
        season=thresholds.vegetation_season,
    )
    return build_recommendation(
        request,
        config,
        climates,
        soil=soil,
        vegetation=vegetation,
        soil_moisture=cached_soil_moisture(location, thresholds),
        recent_rain=cached_recent_rain(location, thresholds),
        water=water,
        irrigation=irrigation,
    )


def least_water_level(
    water: WaterAvailability | None,
    irrigation: IrrigationWater | None,
) -> str | None:
    """The less favourable of the two water indicators (`None` if neither)."""
    levels = [item.level for item in (water, irrigation) if item is not None]
    return min(levels, key=("low", "medium", "high").index) if levels else None


async def _irrigation_or_none() -> IrrigationWater | None:
    """Fail-soft, like the local indicator."""
    try:
        return await fetch_irrigation_water(date.today())
    except UpstreamError:
        return None


async def _water_or_none(location: Location) -> WaterAvailability | None:
    """The water indicator is fail-soft: without it the ranking is the usual one."""
    try:
        return await fetch_water_availability(location, date.today())
    except UpstreamError:
        return None


async def fetch_scenario_climates(
    location: Location,
    scenarios: ScenariosConfig,
) -> dict[ScenarioId, ScenarioClimate]:
    """Monthly climate of every scenario, averaged over its reference years."""
    years = sorted({year for scenario in SCENARIO_IDS for year in scenarios.years_for(scenario)})
    power = PowerClient()
    fetched = await asyncio.gather(
        *(
            power.daily_point(
                location,
                start=date(year, 1, 1),
                end=date(year, 12, 31),
                variables=CLIMATE_VARIABLES,
            )
            for year in years
        )
    )
    series = [one for group in fetched for one in group]
    return {
        scenario: average_monthly_weather(series, scenarios.years_for(scenario))
        for scenario in SCENARIO_IDS
    }


def _soil_findings(
    config: AgroConfig,
    request: RecommendationRequest,
    last_crop: CropConfig,
    soil: SoilProfile | None,
    vegetation: VegetationTrend | None,
    soil_moisture: SoilMoistureState | None,
    texture: SoilTexture | None,
    texture_source: SoilTextureSource | None,
) -> list[str]:
    """What explains the soil state, in the farmer's words."""
    content = config.content
    findings = [
        fill_template(
            template,
            campaigns=request.consecutive_campaigns,
            crop=last_crop.name.lower(),
        )
        for template in (
            content.soil_findings_single_campaign
            if request.consecutive_campaigns == 1
            else content.soil_findings
        )
    ]
    if texture is not None and texture_source == "farmer":
        reported = content.soil_reported_texture_findings.get(texture)
        if reported:
            findings.append(reported)
    if soil is not None:
        values = {
            "sand": round(soil.sand_percent),
            "clay": round(soil.clay_percent),
            "carbon": soil.organic_carbon_g_kg,
        }
        if texture_source == "soilgrids":
            measured = content.soil_texture_findings.get(soil.texture)
            if measured:
                findings.append(fill_template(measured, **values))
        carbon = content.soil_carbon_findings.get(_carbon_band(soil, config.thresholds))
        if carbon:
            findings.append(fill_template(carbon, **values))
    if vegetation is not None:
        trend = content.vegetation_findings.get(vegetation.direction)
        if trend:
            findings.append(
                fill_template(
                    trend,
                    percent=f"{abs(round(vegetation.change_ratio * 100))}%",
                    start_year=vegetation.start_year,
                    end_year=vegetation.end_year,
                )
            )
    if soil_moisture is not None:
        moisture = content.soil_moisture_findings.get(soil_moisture.band)
        if moisture:
            findings.append(
                fill_template(
                    moisture,
                    moisture=soil_moisture.mean_m3_m3,
                    days=soil_moisture.observed_days,
                )
            )
    return findings


def _carbon_band(soil: SoilProfile, thresholds: ThresholdsConfig) -> str:
    shift = carbon_score_shift(soil, thresholds)
    return {-1: "low", 0: "normal", 1: "high"}[shift]


def _data_sources(
    soil: SoilProfile | None,
    vegetation: VegetationTrend | None,
    soil_moisture: SoilMoistureState | None,
    recent_rain: ObservedRain | None,
    texture_source: SoilTextureSource | None,
) -> list[str]:
    sources = ["nasa_power"]
    if soil is not None:
        sources.append(soil.source)
    if vegetation is not None:
        sources.append(vegetation.source)
    if soil_moisture is not None:
        sources.append(soil_moisture.source)
    if recent_rain is not None:
        sources.append(RECENT_RAIN_SOURCE)
    if texture_source == "farmer":
        sources.append("farmer")
    return sources


def _monthly_rain(
    climates: dict[ScenarioId, ScenarioClimate],
) -> dict[ScenarioId, dict[int, float]]:
    return {
        scenario: {month: weather.rain_mm for month, weather in climate.items()}
        for scenario, climate in climates.items()
    }


def _custom_rotation_or_400(
    config: AgroConfig,
    crop_ids: Sequence[str] | None,
) -> list[CropConfig]:
    """The rotation the farmer put together, validated against the catalog."""
    if not crop_ids:
        return []
    limit = config.thresholds.max_custom_rotation_crops
    if len(crop_ids) > limit:
        raise InvalidRequestError(
            f"custom_rotation accepts at most {limit} crops.",
            details={"max_custom_rotation_crops": limit},
        )
    return [_crop_or_400(config, crop_id) for crop_id in crop_ids]


def _ranking_inputs(
    options: Sequence[RotationOptionOut],
    scenario: ScenarioId,
    config: AgroConfig,
    rule_counts: dict[str, int],
) -> list[RankingInput]:
    return [
        RankingInput(
            option_id=option.id,
            irrigation_m3=option.scenarios[scenario].irrigation_m3,
            risk_month_count=option.scenarios[scenario].risk_month_count,
            soil_impact_score=option.soil_impact_score,
            has_high_water_crop=any(
                crop_water_need(config.crop(crop_id), config.thresholds) == "high"
                for crop_id in option.crop_ids
            ),
            worst_risk_month_count=max(
                result.risk_month_count for result in option.scenarios.values()
            ),
            rule_warning_count=rule_counts.get(option.id, 0),
        )
        for option in options
    ]


def _calendar(
    planting_date: date,
    windows: Sequence[CropWindow],
    crops: Sequence[CropConfig],
    thresholds: ThresholdsConfig,
) -> RotationCalendar:
    return RotationCalendar(
        planting_date=planting_date,
        decision_deadline=planting_date - timedelta(days=thresholds.decision_lead_days),
        timeline_start=windows[0].start,
        timeline_months=sum(window.month_count for window in windows),
        periods=[
            CropPeriod(
                crop_id=window.crop.id,
                start=window.start,
                month_count=window.month_count,
            )
            for window in windows
        ],
        instructions=crops[0].planting_instructions,
    )


def _excluded_by(
    config: AgroConfig,
    crops: Sequence[CropConfig],
    by_scenario: dict[ScenarioId, ScenarioResult],
) -> list[str]:
    crop_ids = {crop.id for crop in crops}
    worst_water = max(result.irrigation_m3_per_ha for result in by_scenario.values())
    excluded: list[str] = []
    for restriction in config.restrictions:
        excludes_crop = bool(crop_ids & set(restriction.excludes_crop_ids))
        thirsty = (
            restriction.excludes_high_water_use
            and worst_water > config.thresholds.low_water_m3_per_ha
        )
        if excludes_crop or thirsty:
            excluded.append(restriction.id)
    return excluded


def _horizon_risk_months(planting_date: date, horizon_months: int, risky: set[int]) -> list[date]:
    start = date(planting_date.year, planting_date.month, 1)
    months = [add_months(start, offset) for offset in range(horizon_months)]
    return [month for month in months if month.month in risky]


def _priority_or_400(config: AgroConfig, priority_id: str | None) -> PriorityConfig:
    try:
        return config.priority(priority_id)
    except KeyError as error:
        raise InvalidRequestError(
            f"Unknown priority_id: {priority_id!r}.",
            details={"known": [priority.id for priority in config.priorities]},
        ) from error


def _restrictions_or_400(
    config: AgroConfig, restriction_ids: Sequence[str]
) -> list[RestrictionConfig]:
    try:
        return [config.restriction(restriction_id) for restriction_id in restriction_ids]
    except KeyError as error:
        raise InvalidRequestError(
            f"Unknown restriction_id: {error.args[0]!r}.",
            details={"known": [item.id for item in config.restrictions]},
        ) from error


def _crop_or_400(config: AgroConfig, crop_id: str) -> CropConfig:
    try:
        return config.crop(crop_id)
    except KeyError as error:
        raise InvalidRequestError(
            f"Unknown crop id: {crop_id!r}.",
            details={"known": [crop.id for crop in config.crops]},
        ) from error


def _mid_month_day_of_year(month: int) -> int:
    return date(2001, month, MID_MONTH_DAY).timetuple().tm_yday


def _month_list(months: Sequence[int]) -> str:
    names = [MONTH_NAMES[month - 1] for month in sorted(set(months))]
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} o {names[-1]}"


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)
