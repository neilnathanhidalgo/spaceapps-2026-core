"""How wet the top of the plot has been, from SMAP (AppEEARS).

AppEEARS works with jobs: submit a task, wait minutes, download a CSV. The
recommendation never waits for that. `cached_soil_moisture` reads whatever is
already in the cache and `warm_soil_moisture` moves the job one step forward
after the response is sent: first call submits the task, later ones poll it
and store the window. Once a point is warm, every farmer on it gets the
finding.

The window is the one of `observations.observation_window`, so it only moves
once a month and the task is submitted once per point and month.

What SMAP measures is the water of the first 5 cm, not what the roots have
stored, so it does **not** move the irrigation numbers: it is reported as the
observed state of the plot. Turning it into a water balance is a decision for
the agronomy team.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from ..clients.appeears import (
    SMAP_SOIL_MOISTURE_LAYERS,
    AppEEARSClient,
    normalize_task_status,
)
from ..core.cache import get_cache, make_key, peek
from ..core.config import get_settings
from ..core.errors import SpaceAppsError
from ..core.logging import get_logger
from ..schemas.common import Location, TimeSeries
from ..schemas.recommendation import SoilMoistureBand, SoilMoistureState
from .agro_config import ThresholdsConfig, load_agro_config
from .observations import observation_window

log = get_logger(__name__)

SOIL_MOISTURE_SOURCE = "smap"
TASK_TTL_SECONDS = 30 * 24 * 60 * 60


def moisture_band(mean_m3_m3: float, thresholds: ThresholdsConfig) -> SoilMoistureBand:
    """Dry / normal / wet band of a mean volumetric water content."""
    if mean_m3_m3 < thresholds.soil_moisture_dry_m3_m3:
        return "dry"
    if mean_m3_m3 >= thresholds.soil_moisture_wet_m3_m3:
        return "wet"
    return "normal"


def soil_moisture_state(
    points: Sequence[dict[str, object]],
    thresholds: ThresholdsConfig,
) -> SoilMoistureState | None:
    """Mean of the measured days of the window. `None` when none were valid."""
    measured = [
        (date.fromisoformat(str(point["date"])), float(point["value"]))
        for point in points
        if point.get("value") is not None
    ]
    if not measured:
        return None
    mean = sum(value for _, value in measured) / len(measured)
    return SoilMoistureState(
        mean_m3_m3=round(mean, 3),
        band=moisture_band(mean, thresholds),
        start=min(day for day, _ in measured),
        end=max(day for day, _ in measured),
        observed_days=len(measured),
        source=SOIL_MOISTURE_SOURCE,
    )


def cached_soil_moisture(
    location: Location,
    thresholds: ThresholdsConfig,
    *,
    today: date | None = None,
) -> SoilMoistureState | None:
    """The window if `warm_soil_moisture` already stored it. Never calls AppEEARS."""
    start, end = observation_window(thresholds.observation_window_months, today)
    points = peek(_data_key(location, start, end))
    if points is None:
        return None
    return soil_moisture_state(list(points), thresholds)


async def warm_soil_moisture(location: Location, *, today: date | None = None) -> None:
    """Move the SMAP job of the point one step forward. Fail-soft."""
    if not get_settings().earthdata_configured:
        return

    thresholds = load_agro_config().thresholds
    start, end = observation_window(thresholds.observation_window_months, today)
    data_key = _data_key(location, start, end)
    if peek(data_key) is not None:
        return

    cache = get_cache()
    task_key = _task_key(location, start, end)
    client = AppEEARSClient()
    try:
        task_id = peek(task_key)
        if task_id is None:
            task_id = await client.submit_point_task(
                location=location,
                start=start,
                end=end,
                layers=SMAP_SOIL_MOISTURE_LAYERS,
                task_name=f"semi-smap-{location.lat:.4f}-{location.lon:.4f}-{start:%Y%m}",
            )
            cache.set(task_key, task_id, expire=TASK_TTL_SECONDS)
            log.info("smap_task_submitted", task_id=task_id, start=str(start), end=str(end))
            return

        status = normalize_task_status((await client.get_task(str(task_id))).get("status"))
        if status == "failed":
            # No se vuelve a enviar: la ventana cambia el mes que viene y
            # reintentar en cada petición acabaría limitado por AppEEARS.
            log.warning("smap_task_failed", task_id=str(task_id))
            return
        if status != "done":
            return

        series = await client.point_task_series(str(task_id), SMAP_SOIL_MOISTURE_LAYERS, location)
        points = _points_of(series)
        cache.set(data_key, points, expire=get_settings().cache_ttl_history)
        log.info("smap_window_warmed", days=len(points), start=str(start), end=str(end))
    except SpaceAppsError as error:
        log.warning("smap_unavailable", error=error.message)


def _points_of(series: Sequence[TimeSeries]) -> list[dict[str, object]]:
    return [
        {"date": point.date.isoformat(), "value": point.value}
        for one in series
        for point in one.points
    ]


def _data_key(location: Location, start: date, end: date) -> str:
    return _key("smap:points", location, start, end)


def _task_key(location: Location, start: date, end: date) -> str:
    return _key("smap:task", location, start, end)


def _key(namespace: str, location: Location, start: date, end: date) -> str:
    return make_key(
        namespace,
        {"lat": location.lat, "lon": location.lon, "start": start, "end": end},
    )
