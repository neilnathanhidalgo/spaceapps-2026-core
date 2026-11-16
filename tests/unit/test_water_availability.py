from __future__ import annotations

from datetime import date, timedelta

from spaceapps_core.schemas.common import Location, TimePoint, TimeSeries
from spaceapps_core.schemas.variables import CanonicalVariable
from spaceapps_core.services.recommendation import RankingInput, rank_options
from spaceapps_core.services.water_availability import (
    build_water_availability,
    level_of,
    percentile_rank,
    rain_phrase,
)

POINT = Location(lat=-4.865, lon=-80.72)


def _series(variable: CanonicalVariable, value_for) -> TimeSeries:
    day, end = date(2013, 1, 1), date(2024, 11, 1)
    points = []
    while day < end:
        points.append(TimePoint(date=day, value=value_for(day)))
        day += timedelta(days=1)
    return TimeSeries(source="power", variable=variable, unit="-", location=POINT, points=points)


def _dry_2024(rain_2024: float, wet_2024: float) -> list[TimeSeries]:
    """Every year the same, except May-Oct 2024."""

    def in_window(day: date) -> bool:
        return day.year == 2024 and 5 <= day.month <= 10

    return [
        _series(
            CanonicalVariable.PRECIPITATION,
            lambda day: rain_2024 if in_window(day) else 1.0 + day.year % 3 * 0.1,
        ),
        _series(
            CanonicalVariable.ROOT_ZONE_WETNESS,
            lambda day: wet_2024 if in_window(day) else 0.4 + day.year % 3 * 0.01,
        ),
    ]


def test_percentile_rank_counts_ties_as_half() -> None:
    assert percentile_rank(1, [0, 1, 2, 3]) == 37.5
    assert percentile_rank(-1, [0, 1]) == 0
    assert percentile_rank(9, [0, 1]) == 100


def test_level_is_the_tercile_of_the_mean_rank() -> None:
    assert level_of(0, 60) == "low"
    assert level_of(40, 50) == "medium"
    assert level_of(90, 50) == "high"


def test_rain_phrase_comes_from_the_numbers() -> None:
    assert rain_phrase(10, 30) == "En tu zona llovió menos de la mitad de lo normal estos meses"
    assert rain_phrase(30, 30) == "En tu zona llovió lo normal estos meses"
    assert rain_phrase(90, 30) == "En tu zona llovió más del doble de lo normal estos meses"


def test_a_dry_window_is_low_and_uses_only_data_until_as_of() -> None:
    water = build_water_availability(_dry_2024(rain_2024=0.0, wet_2024=0.2), date(2024, 11, 1))

    assert water is not None
    assert (water.window_start, water.window_end) == (date(2024, 5, 1), date(2024, 10, 31))
    assert water.level == "low"
    assert water.reference_years == list(range(2014, 2024))
    assert water.finding.startswith("En tu zona llovió menos de la mitad de lo normal")
    assert "más seca que en los últimos 10 años" in water.finding


def test_without_ten_reference_years_there_is_no_indicator() -> None:
    short = [
        TimeSeries(
            source="power",
            variable=series.variable,
            unit="-",
            location=POINT,
            points=[point for point in series.points if point.date.year >= 2020],
        )
        for series in _dry_2024(0.0, 0.2)
    ]
    assert build_water_availability(short, date(2024, 11, 1)) is None


def test_with_little_water_options_with_a_thirsty_crop_go_last() -> None:
    inputs = [
        RankingInput("rice-mix", 100, 0, 2, has_high_water_crop=True),
        RankingInput("dry-mix", 900, 0, 0),
    ]

    assert rank_options(inputs, "most_soil_improvement") == ["rice-mix", "dry-mix"]
    assert rank_options(inputs, "most_soil_improvement", water_low=True) == [
        "dry-mix",
        "rice-mix",
    ]


def test_wetness_phrase_names_the_side_most_years_are_on() -> None:
    from spaceapps_core.services.water_availability import wetness_phrase

    reference = [0.1 * year for year in range(1, 11)]
    assert (
        wetness_phrase(0.25, reference) == "la tierra está más seca que en 8 de los últimos 10 años"
    )
    assert (
        wetness_phrase(0.85, reference)
        == "la tierra está más húmeda que en 8 de los últimos 10 años"
    )
