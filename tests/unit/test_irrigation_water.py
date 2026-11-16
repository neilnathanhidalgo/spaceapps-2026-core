from __future__ import annotations

from datetime import date, timedelta

from spaceapps_core.schemas.common import Location, TimePoint, TimeSeries
from spaceapps_core.schemas.recommendation import IrrigationWater, WaterAvailability
from spaceapps_core.schemas.variables import CanonicalVariable
from spaceapps_core.services.irrigation_water import (
    NOTE,
    UPSTREAM_POINTS,
    build_irrigation_water,
    last_season_end_year,
    percent_phrase,
    season_days,
)
from spaceapps_core.services.recommendation import least_water_level


def _rain(value_for) -> list[TimeSeries]:
    day, end = date(2012, 12, 1), date(2024, 11, 1)
    points = []
    while day < end:
        points.append(TimePoint(date=day, value=value_for(day)))
        day += timedelta(days=1)
    return [
        TimeSeries(
            source="power",
            variable=CanonicalVariable.PRECIPITATION,
            unit="mm/day",
            location=Location(lat=-4.6, lon=-79.7),
            points=points,
        )
    ]


def test_the_season_runs_from_december_to_april() -> None:
    days = season_days(2024)
    assert (days[0], days[-1]) == (date(2023, 12, 1), date(2024, 4, 30))
    assert last_season_end_year(date(2024, 11, 1)) == 2024
    assert last_season_end_year(date(2025, 3, 1)) == 2024


def test_a_dry_season_in_the_upper_basin_is_low() -> None:
    dry_2024 = set(season_days(2024))
    series = _rain(lambda day: 1.0 if day in dry_2024 else 5.0 + day.year % 3)
    water = build_irrigation_water(
        [(point, series) for point in UPSTREAM_POINTS], date(2024, 11, 1)
    )

    assert isinstance(water, IrrigationWater)
    assert water.level == "low"
    assert water.reference_seasons == list(range(2014, 2024))
    assert water.percent_vs_normal < -50
    assert water.finding.startswith("En los cerros donde nace tu río llovió")
    assert water.note == NOTE
    assert len(water.points) == len(UPSTREAM_POINTS)


def test_percent_phrase() -> None:
    assert percent_phrase(-39.4) == "llovió 39 % menos de lo normal"
    assert percent_phrase(25) == "llovió 25 % más de lo normal"
    assert percent_phrase(-5) == "llovió casi lo normal"


def test_the_ranking_uses_the_less_favourable_indicator() -> None:
    def local(level: str) -> WaterAvailability:
        return WaterAvailability.model_construct(level=level)

    def basin(level: str) -> IrrigationWater:
        return IrrigationWater.model_construct(level=level)

    assert least_water_level(local("high"), basin("low")) == "low"
    assert least_water_level(local("medium"), basin("high")) == "medium"
    assert least_water_level(None, basin("medium")) == "medium"
    assert least_water_level(None, None) is None
