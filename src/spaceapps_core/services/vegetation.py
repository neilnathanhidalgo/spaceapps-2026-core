"""Greenness trend of the plot from MODIS NDVI (ORNL DAAC).

Answers "is my field greening up or running down?" by comparing the mean
NDVI of the growing season of the first and the last year of the window.
Simple on purpose: it has to be explainable to the farmer ("tu verdor bajó
18% en 5 años").

The ORNL service answers synchronously but can take tens of seconds, so the
recommendation never waits for it: it uses the windows that are already
cached (`cached_vegetation_trend`) and the endpoint refreshes them in the
background (`warm_vegetation_trend`). Once a point is warm every farmer on
it gets the finding.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import date, timedelta

from ..clients.ornl_modis import OrnlModisClient
from ..core.errors import SpaceAppsError
from ..core.logging import get_logger
from ..schemas.common import Location, TimeSeries
from ..schemas.recommendation import VegetationDirection, VegetationTrend

log = get_logger(__name__)


def annual_means(series: TimeSeries) -> dict[int, float]:
    """Mean NDVI per calendar year, skipping missing composites."""
    totals: dict[int, list[float]] = {}
    for point in series.points:
        if point.value is None:
            continue
        totals.setdefault(point.date.year, []).append(point.value)
    return {year: sum(values) / len(values) for year, values in totals.items()}


def vegetation_trend(
    series: TimeSeries,
    *,
    flat_tolerance: float,
    min_years: int = 2,
) -> VegetationTrend | None:
    """Compare the first and last year of the series.

    Returns `None` when there are fewer than `min_years` years with data, or
    when the first year's mean is not usable as a reference.
    """
    means = annual_means(series)
    if len(means) < min_years:
        return None

    years = sorted(means)
    start_year, end_year = years[0], years[-1]
    start, end = means[start_year], means[end_year]
    if start <= 0:
        return None

    change = (end - start) / start
    return VegetationTrend(
        start_year=start_year,
        end_year=end_year,
        start_ndvi=round(start, 3),
        end_ndvi=round(end, 3),
        change_ratio=round(change, 3),
        direction=_direction(change, flat_tolerance),
    )


def _direction(change: float, flat_tolerance: float) -> VegetationDirection:
    if change <= -flat_tolerance:
        return "down"
    if change >= flat_tolerance:
        return "up"
    return "flat"


def season_windows(
    *,
    years: int,
    season: tuple[int, int],
    today: date | None = None,
) -> list[tuple[date, date]]:
    """Growing-season window of the first and the last year compared.

    Only those two are downloaded: the trend does not need the years in
    between, and a shorter window is what the ORNL service answers best.
    """
    end = today or date.today()
    first_month, last_month = season
    # "los últimos 5 años" = de hace 5 años a hoy.
    years_wanted = [end.year - years, end.year]
    windows: list[tuple[date, date]] = []
    for year in years_wanted:
        start = date(year, first_month, 1)
        finish = min(_end_of_month(year, last_month), end)
        if start < finish:
            windows.append((start, finish))
    return windows


def _end_of_month(year: int, month: int) -> date:
    return date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)


def _merge(series: Sequence[TimeSeries]) -> TimeSeries:
    points = [point for one in series for point in one.points]
    return series[0].model_copy(update={"points": points})


def cached_vegetation_trend(
    location: Location,
    *,
    years: int,
    flat_tolerance: float,
    season: tuple[int, int],
    today: date | None = None,
) -> VegetationTrend | None:
    """Trend from the windows already cached. Never contacts the service."""
    client = OrnlModisClient()
    windows = season_windows(years=years, season=season, today=today)
    series = [client.cached_ndvi_point(location, start, end) for start, end in windows]
    if len(series) < 2 or any(one is None for one in series):
        return None
    return vegetation_trend(
        _merge([one for one in series if one is not None]),
        flat_tolerance=flat_tolerance,
    )


async def fetch_vegetation_trend(
    location: Location,
    *,
    years: int,
    flat_tolerance: float,
    season: tuple[int, int],
    today: date | None = None,
) -> VegetationTrend | None:
    """Download the two windows (in parallel) and reduce them. Fail-soft."""
    client = OrnlModisClient()
    windows = season_windows(years=years, season=season, today=today)
    if len(windows) < 2:
        return None
    try:
        series = await asyncio.gather(
            *(client.ndvi_point(location, start, end) for start, end in windows)
        )
    except SpaceAppsError as error:
        log.warning("vegetation_trend_unavailable", error=error.message)
        return None
    return vegetation_trend(_merge(series), flat_tolerance=flat_tolerance)


async def warm_vegetation_trend(location: Location) -> None:
    """Fill the NDVI cache for the point, to be used as a background task."""
    from .agro_config import load_agro_config

    thresholds = load_agro_config().thresholds
    trend = await fetch_vegetation_trend(
        location,
        years=thresholds.vegetation_trend_years,
        flat_tolerance=thresholds.vegetation_flat_tolerance,
        season=thresholds.vegetation_season,
    )
    log.info("vegetation_trend_warmed", lat=location.lat, lon=location.lon, found=trend is not None)
