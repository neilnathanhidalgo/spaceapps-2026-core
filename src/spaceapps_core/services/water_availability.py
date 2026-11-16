"""Water available at a point, from NASA POWER only.

The rule is fixed in advance, so no result is tuned to look good:

1. Window: the last `WINDOW_MONTHS` complete calendar months before `as_of`
   for which POWER has at least `MIN_COVERAGE` of valid days in both
   variables (POWER lags a few weeks; a half-empty month is not compared).
2. Observed: total rain (PRECTOTCORR) and mean root-zone wetness
   (GWETROOT) over the window.
3. Reference: the same calendar window in each of the `REFERENCE_YEARS`
   previous years.
4. Each observed value gets its percentile rank among the reference
   values; the level is the tercile of the mean of both ranks
   (< 33.3 low, > 66.7 high, otherwise medium).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from ..clients.power import PowerClient
from ..schemas.common import Location, TimeSeries
from ..schemas.recommendation import WaterAvailability, WaterLevel
from ..schemas.variables import CanonicalVariable
from .observations import add_months

WINDOW_MONTHS = 6
REFERENCE_YEARS = 10
MIN_COVERAGE = 0.9
LOW_TERCILE = 100 / 3
HIGH_TERCILE = 200 / 3
VARIABLES = [CanonicalVariable.PRECIPITATION, CanonicalVariable.ROOT_ZONE_WETNESS]


@dataclass(frozen=True)
class _Daily:
    rain: dict[date, float]
    wetness: dict[date, float]


def _daily(series: Iterable[TimeSeries]) -> _Daily:
    rain: dict[date, float] = {}
    wetness: dict[date, float] = {}
    for one in series:
        target = rain if one.variable is CanonicalVariable.PRECIPITATION else wetness
        for point in one.points:
            if point.value is not None:
                target[point.date] = point.value
    return _Daily(rain=rain, wetness=wetness)


def _days(start: date, months: int) -> list[date]:
    end = add_months(start, months)
    return [date.fromordinal(day) for day in range(start.toordinal(), end.toordinal())]


def _complete(daily: _Daily, month_start: date) -> bool:
    days = _days(month_start, 1)
    rain = sum(day in daily.rain for day in days)
    wet = sum(day in daily.wetness for day in days)
    return min(rain, wet) >= MIN_COVERAGE * len(days)


def last_complete_window_start(daily: _Daily, as_of: date) -> date | None:
    """First month of the latest window whose months are all complete."""
    last = add_months(date(as_of.year, as_of.month, 1), -1)
    for _ in range(3):  # POWER no se atrasa más de un par de meses.
        start = add_months(last, -(WINDOW_MONTHS - 1))
        months = [add_months(start, offset) for offset in range(WINDOW_MONTHS)]
        if all(_complete(daily, month) for month in months):
            return start
        last = add_months(last, -1)
    return None


def _window_values(daily: _Daily, start: date) -> tuple[float, float]:
    days = _days(start, WINDOW_MONTHS)
    rain = sum(daily.rain.get(day, 0.0) for day in days)
    wet = [daily.wetness[day] for day in days if day in daily.wetness]
    return rain, sum(wet) / len(wet)


def percentile_rank(value: float, reference: Sequence[float]) -> float:
    """Share of the reference below `value` (ties count half), 0-100."""
    below = sum(other < value for other in reference)
    equal = sum(other == value for other in reference)
    return 100 * (below + 0.5 * equal) / len(reference)


def level_of(rain_percentile: float, wetness_percentile: float) -> WaterLevel:
    mean = (rain_percentile + wetness_percentile) / 2
    if mean < LOW_TERCILE:
        return "low"
    if mean > HIGH_TERCILE:
        return "high"
    return "medium"


def rain_phrase(rain_mm: float, normal_mm: float) -> str:
    """How the rain compares with normal, in the farmer's words."""
    if normal_mm <= 0:
        return "En tu zona casi nunca llueve en estos meses"
    ratio = rain_mm / normal_mm
    if ratio < 0.5:
        return "En tu zona llovió menos de la mitad de lo normal estos meses"
    if ratio < 0.9:
        return "En tu zona llovió menos de lo normal estos meses"
    if ratio <= 1.1:
        return "En tu zona llovió lo normal estos meses"
    if ratio <= 2:
        return "En tu zona llovió más de lo normal estos meses"
    return "En tu zona llovió más del doble de lo normal estos meses"


def wetness_phrase(wetness: float, reference: Sequence[float]) -> str:
    wetter_years = sum(other > wetness for other in reference)
    if wetter_years == len(reference):
        return f"la tierra está más seca que en los últimos {len(reference)} años"
    if wetter_years == 0:
        return f"la tierra está más húmeda que en los últimos {len(reference)} años"
    drier_years = len(reference) - wetter_years
    if wetter_years >= drier_years:
        return f"la tierra está más seca que en {wetter_years} de los últimos {len(reference)} años"
    return f"la tierra está más húmeda que en {drier_years} de los últimos {len(reference)} años"


def build_water_availability(series: Iterable[TimeSeries], as_of: date) -> WaterAvailability | None:
    """Indicator for the window before `as_of`. `None` if POWER lacks the data."""
    daily = _daily(series)
    start = last_complete_window_start(daily, as_of)
    if start is None:
        return None
    rain, wetness = _window_values(daily, start)
    references: list[tuple[int, float, float]] = []
    for years_back in range(1, REFERENCE_YEARS + 1):
        ref_start = date(start.year - years_back, start.month, 1)
        if all(_complete(daily, add_months(ref_start, offset)) for offset in range(WINDOW_MONTHS)):
            ref_rain, ref_wet = _window_values(daily, ref_start)
            references.append((ref_start.year, ref_rain, ref_wet))
    if len(references) < REFERENCE_YEARS:
        return None
    rains = [ref[1] for ref in references]
    wets = [ref[2] for ref in references]
    rain_pct = percentile_rank(rain, rains)
    wet_pct = percentile_rank(wetness, wets)
    normal_rain = sum(rains) / len(rains)
    return WaterAvailability(
        level=level_of(rain_pct, wet_pct),
        window_start=start,
        window_end=date.fromordinal(add_months(start, WINDOW_MONTHS).toordinal() - 1),
        rain_mm=round(rain, 1),
        rain_normal_mm=round(normal_rain, 1),
        rain_percentile=round(rain_pct, 1),
        root_wetness=round(wetness, 3),
        root_wetness_normal=round(sum(wets) / len(wets), 3),
        root_wetness_percentile=round(wet_pct, 1),
        reference_years=sorted(ref[0] for ref in references),
        finding=f"{rain_phrase(rain, normal_rain)} y {wetness_phrase(wetness, wets)}.",
    )


async def fetch_water_availability(location: Location, as_of: date) -> WaterAvailability | None:
    """Fetch POWER daily rain and root wetness and build the indicator."""
    start = date(as_of.year - REFERENCE_YEARS - 1, 1, 1)
    # Solo hasta el día anterior a `as_of`: nada posterior entra al cálculo.
    end = as_of - timedelta(days=1)
    series = await PowerClient().daily_point(location, start=start, end=end, variables=VARIABLES)
    return build_water_availability(series, as_of)
