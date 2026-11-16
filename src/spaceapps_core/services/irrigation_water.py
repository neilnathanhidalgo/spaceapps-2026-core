"""Water that reaches the Chira valley through irrigation, approximated with rain.

The valley is irrigated from Poechos, which fills with the river born in the
upper Chira-Catamayo basin (Ayabaca in Peru, Loja in Ecuador). Without the
reservoir level, this indicator looks at the rain where that water comes
from. The rule is fixed in advance:

1. Season: December to April (`SEASON_MONTHS`), the main rains of the upper
   basin. The last season that ended before `as_of` with at least
   `MIN_COVERAGE` of valid days at every point.
2. Observed: the season's total rain at each point (NASA POWER PRECTOTCORR),
   averaged over the points.
3. Reference: the same season of the `REFERENCE_SEASONS` previous years.
4. Level: tercile of the percentile rank of the observed value among the
   reference values (< 33.3 low, > 66.7 high, otherwise medium).

It is an approximation with rain, not the real level of the reservoir.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from ..clients.power import PowerClient
from ..schemas.common import Location, TimeSeries
from ..schemas.recommendation import BasinPoint, IrrigationWater, WaterLevel
from ..schemas.variables import CanonicalVariable
from .water_availability import HIGH_TERCILE, LOW_TERCILE, percentile_rank

SEASON_START_MONTH = 12
SEASON_MONTHS = 5  # diciembre a abril
REFERENCE_SEASONS = 10
MIN_COVERAGE = 0.9
NOTE = "Es una aproximación con la lluvia de la cuenca alta, no el nivel real de Poechos."


@dataclass(frozen=True)
class UpstreamPoint:
    name: str
    lat: float
    lon: float


UPSTREAM_POINTS: tuple[UpstreamPoint, ...] = (
    # Cuatro celdas distintas de NASA POWER (0.5 x 0.625 grados) en la cuenca
    # alta del Chira-Catamayo, aguas arriba de Poechos. Ayabaca comparte celda
    # con Macará y Sozoranga; Catamayo, con Gonzanamá.
    UpstreamPoint("Ayabaca (Perú)", -4.64, -79.72),
    UpstreamPoint("Pacaipampa, cabecera del Quiroz (Perú)", -4.99, -79.67),
    UpstreamPoint("Cariamanga, río Calvas (Ecuador)", -4.33, -79.55),
    UpstreamPoint("Catamayo, cabecera del Catamayo (Ecuador)", -3.99, -79.36),
)


def season_days(season_end_year: int) -> list[date]:
    """Days of the season that ends in April of `season_end_year`."""
    start = date(season_end_year - 1, SEASON_START_MONTH, 1)
    end = date(season_end_year, SEASON_START_MONTH + SEASON_MONTHS - 12, 1)
    return [date.fromordinal(day) for day in range(start.toordinal(), end.toordinal())]


def _rain_by_day(series: Iterable[TimeSeries]) -> dict[date, float]:
    return {
        point.date: point.value
        for one in series
        if one.variable is CanonicalVariable.PRECIPITATION
        for point in one.points
        if point.value is not None
    }


def _season_total(rain: dict[date, float], season_end_year: int) -> float | None:
    days = season_days(season_end_year)
    present = [rain[day] for day in days if day in rain]
    if len(present) < MIN_COVERAGE * len(days):
        return None
    return sum(present)


def last_season_end_year(as_of: date) -> int:
    """Year whose April closes the last season that ended before `as_of`."""
    return as_of.year if as_of > date(as_of.year, 4, 30) else as_of.year - 1


def percent_phrase(percent: float) -> str:
    if abs(percent) < 10:
        return "llovió casi lo normal"
    if percent < 0:
        return f"llovió {round(-percent)} % menos de lo normal"
    return f"llovió {round(percent)} % más de lo normal"


def level_of(percentile: float) -> WaterLevel:
    if percentile < LOW_TERCILE:
        return "low"
    if percentile > HIGH_TERCILE:
        return "high"
    return "medium"


def build_irrigation_water(
    series_by_point: Sequence[tuple[UpstreamPoint, Iterable[TimeSeries]]],
    as_of: date,
) -> IrrigationWater | None:
    """Indicator for the last season before `as_of`. `None` if data is missing."""
    rains = [(point, _rain_by_day(series)) for point, series in series_by_point]
    season = last_season_end_year(as_of)
    for _ in range(2):  # si la última temporada aún no está completa, la anterior
        observed = [_season_total(rain, season) for _, rain in rains]
        if all(total is not None for total in observed):
            break
        season -= 1
    else:
        return None

    references: list[tuple[int, float]] = []
    per_point_reference: list[list[float]] = [[] for _ in rains]
    for year in range(season - REFERENCE_SEASONS, season):
        totals = [_season_total(rain, year) for _, rain in rains]
        if any(total is None for total in totals):
            continue
        for index, total in enumerate(totals):
            per_point_reference[index].append(total)  # type: ignore[arg-type]
        references.append((year, sum(totals) / len(totals)))  # type: ignore[arg-type]
    if len(references) < REFERENCE_SEASONS:
        return None

    basin_rain = sum(observed) / len(observed)  # type: ignore[arg-type]
    reference_values = [value for _, value in references]
    normal = sum(reference_values) / len(reference_values)
    percent = (basin_rain / normal - 1) * 100 if normal > 0 else 0.0
    percentile = percentile_rank(basin_rain, reference_values)
    days = season_days(season)
    return IrrigationWater(
        level=level_of(percentile),
        season_start=days[0],
        season_end=days[-1],
        rain_mm=round(basin_rain, 1),
        rain_normal_mm=round(normal, 1),
        percent_vs_normal=round(percent, 1),
        rain_percentile=round(percentile, 1),
        reference_seasons=[year for year, _ in references],
        points=[
            BasinPoint(
                name=point.name,
                lat=point.lat,
                lon=point.lon,
                rain_mm=round(total, 1),  # type: ignore[arg-type]
                rain_normal_mm=round(sum(ref) / len(ref), 1),
            )
            for (point, _), total, ref in zip(rains, observed, per_point_reference, strict=True)
        ],
        finding=(
            f"En los cerros donde nace tu río {percent_phrase(percent)} en la última "
            "temporada de lluvias (diciembre a abril)."
        ),
        note=NOTE,
    )


async def fetch_irrigation_water(as_of: date) -> IrrigationWater | None:
    """Fetch the basin points from NASA POWER and build the indicator."""
    season = last_season_end_year(as_of)
    start = date(season - REFERENCE_SEASONS - 2, SEASON_START_MONTH, 1)
    end = as_of - timedelta(days=1)
    power = PowerClient()
    fetched = await asyncio.gather(
        *(
            power.daily_point(
                Location(lat=point.lat, lon=point.lon),
                start=start,
                end=end,
                variables=[CanonicalVariable.PRECIPITATION],
            )
            for point in UPSTREAM_POINTS
        )
    )
    return build_irrigation_water(list(zip(UPSTREAM_POINTS, fetched, strict=True)), as_of)
