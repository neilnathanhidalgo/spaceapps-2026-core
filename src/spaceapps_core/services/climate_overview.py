"""Climate summary for the mobile app's "Clima" screen.

Combines the Open-Meteo short-term forecast with NASA POWER recent daily
observations compared against the POWER long-term monthly climatology.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import date, datetime, timedelta

from ..clients.open_meteo import OpenMeteoClient
from ..clients.power import PowerClient
from ..core.errors import SpaceAppsError, UpstreamError
from ..core.logging import get_logger
from ..schemas.climate_overview import (
    ClimateAnomaly,
    ClimateMetric,
    ClimateOverview,
    DailyForecast,
    DegreesFromNormal,
    MoistureCategory,
    SoilMoistureLevel,
    TimesNormal,
    TodayWeather,
    WeatherCondition,
)
from ..schemas.common import Location, TimePoint, TimeSeries
from ..schemas.variables import CanonicalVariable

FORECAST_DAYS = 7
ANOMALY_WINDOW_DAYS = 30
POWER_LOOKBACK_DAYS = 45
MIN_VALID_DAYS = 7

HEAVY_RAIN_MM = 30.0
MODERATE_RAIN_MM = 10.0
LIGHT_RAIN_MM = 1.0
CLEAR_SKY_WMO_CODES = {0, 1}

RAIN_NOISE_MM = 1.0
MIN_RAIN_FACTOR = 0.1
MAX_RAIN_FACTOR = 10.0
BAR_HEADROOM = 0.9
TEMPERATURE_BAR_RANGE_C = 8.0
SOIL_WETNESS_STEP = 0.1

FORECAST_VARIABLES = [
    CanonicalVariable.T2M_MAX,
    CanonicalVariable.PRECIPITATION,
    CanonicalVariable.PRECIPITATION_PROBABILITY,
    CanonicalVariable.WEATHER_CODE,
]
ANOMALY_VARIABLES = [
    CanonicalVariable.PRECIPITATION,
    CanonicalVariable.T2M_MEAN,
    CanonicalVariable.SOIL_WETNESS,
]

SPANISH_WEEKDAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

log = get_logger(__name__)


async def build_climate_overview(location: Location) -> ClimateOverview:
    days, anomalies = await asyncio.gather(
        _fetch_daily_weather(location),
        _fetch_anomalies_or_empty(location, today=date.today()),
    )
    if not days:
        raise UpstreamError("Open-Meteo returned an empty forecast.")

    week = [DailyForecast(date=d.date, condition=d.condition, rain_mm=d.rain_mm) for d in days]
    return ClimateOverview(
        location=location,
        today=days[0],
        week=week,
        advice=build_advice(week, _soil_level(anomalies)),
        anomalies=anomalies,
        sources=["open_meteo", "nasa_power"],
        generated_at=datetime.utcnow(),
    )


async def _fetch_daily_weather(location: Location) -> list[TodayWeather]:
    series = await OpenMeteoClient().forecast(
        location,
        forecast_days=FORECAST_DAYS,
        variables=FORECAST_VARIABLES,
        timezone="auto",
    )
    by_variable = {s.variable: s.points for s in series}
    rain = by_variable[CanonicalVariable.PRECIPITATION]
    days: list[TodayWeather] = []
    for index, point in enumerate(rain):
        rain_mm = max(point.value or 0.0, 0.0)
        code = _value_at(by_variable[CanonicalVariable.WEATHER_CODE], index)
        probability = _value_at(by_variable[CanonicalVariable.PRECIPITATION_PROBABILITY], index)
        temperature = _value_at(by_variable[CanonicalVariable.T2M_MAX], index)
        days.append(
            TodayWeather(
                date=point.date,
                condition=classify_day(rain_mm, code),
                rain_probability=(probability or 0.0) / 100,
                rain_mm=round(rain_mm, 1),
                temperature_c=round(temperature or 0.0),
            )
        )
    return days


def _value_at(points: list[TimePoint], index: int) -> float | None:
    return points[index].value if index < len(points) else None


def _soil_level(anomalies: list[ClimateAnomaly]) -> SoilMoistureLevel | None:
    for anomaly in anomalies:
        if isinstance(anomaly.comparison, MoistureCategory):
            return anomaly.comparison.level
    return None


def classify_day(rain_mm: float, weather_code: float | None) -> WeatherCondition:
    if rain_mm >= HEAVY_RAIN_MM:
        return "heavy_rain"
    if rain_mm >= MODERATE_RAIN_MM:
        return "moderate_rain"
    if rain_mm >= LIGHT_RAIN_MM:
        return "rain"
    if weather_code is None or int(weather_code) in CLEAR_SKY_WMO_CODES:
        return "sunny"
    return "cloudy"


def build_advice(week: list[DailyForecast], soil_level: SoilMoistureLevel | None) -> str:
    storm = next((day for day in week if day.condition == "heavy_rain"), None)
    if storm is not None:
        resume_day = SPANISH_WEEKDAYS[(storm.date + timedelta(days=1)).weekday()]
        advice = f"no siembres ni abones hasta el {resume_day}."
        if soil_level == "very_wet":
            advice += " Tu suelo ya está muy húmedo."
        return advice
    if any(day.condition in ("rain", "moderate_rain") for day in week):
        return "aprovecha los días sin lluvia para sembrar y abonar."
    if soil_level == "dry":
        return "no se espera lluvia esta semana y tu suelo está seco: planifica tu riego."
    return "buena semana para trabajar la tierra; no se espera lluvia fuerte."


async def _fetch_anomalies_or_empty(location: Location, *, today: date) -> list[ClimateAnomaly]:
    try:
        return await _fetch_anomalies(location, today=today)
    except SpaceAppsError as error:
        log.warning("climate_anomalies_unavailable", error=error.message)
        return []


async def _fetch_anomalies(location: Location, *, today: date) -> list[ClimateAnomaly]:
    power = PowerClient()
    observed, climatology = await asyncio.gather(
        power.daily_point(
            location,
            start=today - timedelta(days=POWER_LOOKBACK_DAYS),
            end=today - timedelta(days=1),
            variables=ANOMALY_VARIABLES,
        ),
        power.climatology_point(location, variables=ANOMALY_VARIABLES),
    )
    observed_by_variable = {s.variable: s for s in observed}
    normals_by_variable = {s.variable: _monthly_normals(s) for s in climatology}

    builders: list[tuple[CanonicalVariable, Callable[..., ClimateAnomaly]]] = [
        (CanonicalVariable.PRECIPITATION, rainfall_anomaly),
        (CanonicalVariable.T2M_MEAN, temperature_anomaly),
        (CanonicalVariable.SOIL_WETNESS, soil_moisture_anomaly),
    ]
    anomalies: list[ClimateAnomaly] = []
    for variable, build in builders:
        series = observed_by_variable.get(variable)
        normals = normals_by_variable.get(variable)
        if series is None or not normals:
            continue
        window = _recent_valid_points(series)
        if len(window) < MIN_VALID_DAYS or any(p.date.month not in normals for p in window):
            continue
        anomalies.append(build(window, normals, series.unit))
    return anomalies


def _monthly_normals(series: TimeSeries) -> dict[int, float]:
    return {p.date.month: p.value for p in series.points if p.value is not None}


def _recent_valid_points(series: TimeSeries) -> list[TimePoint]:
    valid = [p for p in series.points if p.value is not None]
    return valid[-ANOMALY_WINDOW_DAYS:]


def _observed_and_normal(
    window: list[TimePoint], normals: dict[int, float]
) -> tuple[list[float], list[float]]:
    observed = [p.value for p in window if p.value is not None]
    normal = [normals[p.date.month] for p in window]
    return observed, normal


def _anomaly(
    metric: ClimateMetric,
    window: list[TimePoint],
    observed: float,
    normal: float,
    observed_level: float,
    normal_level: float,
    comparison: TimesNormal | DegreesFromNormal | MoistureCategory,
    unit: str,
) -> ClimateAnomaly:
    return ClimateAnomaly(
        metric=metric,
        observed_level=_clamp(observed_level),
        normal_level=_clamp(normal_level),
        comparison=comparison,
        observed_value=round(observed, 2),
        normal_value=round(normal, 2),
        unit=unit,
        period_start=window[0].date,
        period_end=window[-1].date,
    )


def rainfall_anomaly(
    window: list[TimePoint], normals: dict[int, float], unit: str
) -> ClimateAnomaly:
    observed_daily, normal_daily = _observed_and_normal(window, normals)
    observed, normal = sum(observed_daily), sum(normal_daily)
    scale = max(observed, normal) / BAR_HEADROOM or 1.0
    return _anomaly(
        "rainfall",
        window,
        observed,
        normal,
        observed / scale,
        normal / scale,
        TimesNormal(factor=times_normal(observed, normal)),
        "mm",
    )


def times_normal(observed: float, normal: float) -> float:
    if abs(observed - normal) < RAIN_NOISE_MM:
        return 1.0
    factor = observed / max(normal, RAIN_NOISE_MM)
    return round(min(max(factor, MIN_RAIN_FACTOR), MAX_RAIN_FACTOR), 1)


def temperature_anomaly(
    window: list[TimePoint], normals: dict[int, float], unit: str
) -> ClimateAnomaly:
    observed_daily, normal_daily = _observed_and_normal(window, normals)
    observed, normal = _mean(observed_daily), _mean(normal_daily)
    delta = round(observed - normal, 1)
    return _anomaly(
        "temperature",
        window,
        observed,
        normal,
        0.5 + delta / (2 * TEMPERATURE_BAR_RANGE_C),
        0.5,
        DegreesFromNormal(delta=delta),
        unit,
    )


def soil_moisture_anomaly(
    window: list[TimePoint], normals: dict[int, float], unit: str
) -> ClimateAnomaly:
    observed_daily, normal_daily = _observed_and_normal(window, normals)
    observed, normal = _mean(observed_daily), _mean(normal_daily)
    return _anomaly(
        "soil_moisture",
        window,
        observed,
        normal,
        observed,
        normal,
        MoistureCategory(level=moisture_level(observed - normal)),
        unit,
    )


def moisture_level(difference: float) -> SoilMoistureLevel:
    if difference <= -SOIL_WETNESS_STEP:
        return "dry"
    if difference < SOIL_WETNESS_STEP:
        return "normal"
    if difference < 2 * SOIL_WETNESS_STEP:
        return "wet"
    return "very_wet"


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _clamp(value: float) -> float:
    return min(max(value, 0.0), 1.0)
