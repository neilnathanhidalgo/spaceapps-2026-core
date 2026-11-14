from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from .common import Location

WeatherCondition = Literal["sunny", "cloudy", "rain", "moderate_rain", "heavy_rain"]
ClimateMetric = Literal["rainfall", "temperature", "soil_moisture"]
SoilMoistureLevel = Literal["dry", "normal", "wet", "very_wet"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TodayWeather(_Strict):
    date: date
    condition: WeatherCondition
    rain_probability: float = Field(..., ge=0, le=1)
    rain_mm: float = Field(..., ge=0)
    temperature_c: float = Field(..., description="Daily maximum temperature at 2 m.")


class DailyForecast(_Strict):
    date: date
    condition: WeatherCondition
    rain_mm: float = Field(..., ge=0)


class TimesNormal(_Strict):
    type: Literal["times_normal"] = "times_normal"
    factor: float = Field(..., gt=0, description="1 = normal; 3 = three times the normal.")


class DegreesFromNormal(_Strict):
    type: Literal["degrees_from_normal"] = "degrees_from_normal"
    delta: float = Field(..., description="Difference with the normal in degC.")


class MoistureCategory(_Strict):
    type: Literal["moisture_category"] = "moisture_category"
    level: SoilMoistureLevel


AnomalyComparison = Annotated[
    TimesNormal | DegreesFromNormal | MoistureCategory,
    Field(discriminator="type"),
]


class ClimateAnomaly(_Strict):
    metric: ClimateMetric
    observed_level: float = Field(..., ge=0, le=1, description="Bar position of the observation.")
    normal_level: float = Field(..., ge=0, le=1, description="Bar position of the normal.")
    comparison: AnomalyComparison
    observed_value: float
    normal_value: float
    unit: str
    period_start: date
    period_end: date


class ClimateOverview(_Strict):
    location: Location
    today: TodayWeather
    week: list[DailyForecast]
    advice: str = Field(..., description="Practical advice in Spanish, lowercase first letter.")
    anomalies: list[ClimateAnomaly]
    sources: list[str]
    generated_at: datetime
