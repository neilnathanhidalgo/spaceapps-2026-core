"""Rain already measured over the plot, from GPM IMERG.

IMERG sees 0.1 degrees against NASA POWER's 0.5, so it is the finer look at
what this campaign actually got. It answers the question behind the three
scenarios: does the rain of the last months look like a wet, a normal or a
dry year?

Reading it means opening one granule per day, which takes minutes, so it
follows the same path as the NDVI trend: the recommendation uses the window
already cached (`cached_recent_rain`) and the endpoint refreshes it in the
background (`warm_recent_rain`). The final IMERG run lags about a month, so
the window of `observations.observation_window` is what is actually there.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ..clients.earthdata import EarthdataClient
from ..core.config import get_settings
from ..core.errors import SpaceAppsError
from ..core.logging import get_logger
from ..schemas.common import Location, TimeSeries
from ..schemas.recommendation import SCENARIO_IDS, RecentRain, ScenarioId
from .agro_config import ContentConfig, ThresholdsConfig, fill_template, load_agro_config
from .observations import observation_window

log = get_logger(__name__)

RECENT_RAIN_SOURCE = "gpm_imerg"
DAYS_IN_MONTH_FOR_SHARE = {
    month: (date(2001, month % 12 + 1, 1) - date(2001, month, 1)).days for month in range(1, 13)
}


@dataclass(frozen=True)
class ObservedRain:
    """What IMERG actually measured inside the window."""

    total_mm: float
    observed_days: int
    start: date
    end: date
    days_by_month: dict[int, int]


def observed_rain(series: TimeSeries, start: date, end: date) -> ObservedRain | None:
    """Add up the measured days of the window. `None` when there are none."""
    measured = [
        (point.date, point.value)
        for point in series.points
        if point.value is not None and start <= point.date <= end
    ]
    if not measured:
        return None
    days_by_month: dict[int, int] = {}
    for day, _ in measured:
        days_by_month[day.month] = days_by_month.get(day.month, 0) + 1
    return ObservedRain(
        total_mm=round(sum(value for _, value in measured), 1),
        observed_days=len(measured),
        start=min(day for day, _ in measured),
        end=max(day for day, _ in measured),
        days_by_month=days_by_month,
    )


def expected_totals(
    days_by_month: dict[int, int],
    monthly_rain: dict[ScenarioId, dict[int, float]],
) -> dict[ScenarioId, float]:
    """What the same days add up to in each scenario's reference years.

    The scenario only knows whole months, so each one contributes the share
    of its rain that the measured days cover.
    """
    return {
        scenario: round(
            sum(
                rain_by_month.get(month, 0.0) * days / DAYS_IN_MONTH_FOR_SHARE[month]
                for month, days in days_by_month.items()
            ),
            1,
        )
        for scenario, rain_by_month in monthly_rain.items()
    }


def closest_scenario(total_mm: float, totals: dict[ScenarioId, float]) -> ScenarioId:
    """Scenario whose expected total is nearest to what was measured."""
    return min(SCENARIO_IDS, key=lambda scenario: abs(totals[scenario] - total_mm))


def build_recent_rain(
    rain: ObservedRain,
    monthly_rain: dict[ScenarioId, dict[int, float]],
    content: ContentConfig,
) -> RecentRain:
    """Join the measurement, the comparison and the text for the farmer."""
    totals = expected_totals(rain.days_by_month, monthly_rain)
    scenario = closest_scenario(rain.total_mm, totals)
    return RecentRain(
        start=rain.start,
        end=rain.end,
        observed_days=rain.observed_days,
        total_mm=rain.total_mm,
        scenario_totals=totals,
        closest_scenario=scenario,
        finding=fill_template(
            content.recent_rain_findings.get(scenario, ""),
            total=rain.total_mm,
            days=rain.observed_days,
        ),
        source=RECENT_RAIN_SOURCE,
    )


def cached_recent_rain(
    location: Location,
    thresholds: ThresholdsConfig,
    *,
    today: date | None = None,
) -> ObservedRain | None:
    """The window if it is already cached. Never contacts Earthdata."""
    start, end = observation_window(thresholds.observation_window_months, today)
    series = EarthdataClient().cached_imerg_daily_point(location=location, start=start, end=end)
    if series is None:
        return None
    return observed_rain(series, start, end)


async def warm_recent_rain(location: Location, *, today: date | None = None) -> None:
    """Fill the IMERG cache for the point, to be used as a background task."""
    if not get_settings().earthdata_configured:
        return

    thresholds = load_agro_config().thresholds
    start, end = observation_window(thresholds.observation_window_months, today)
    try:
        series = await EarthdataClient().imerg_daily_point(location=location, start=start, end=end)
    except SpaceAppsError as error:
        log.warning("recent_rain_unavailable", error=error.message)
        return
    log.info(
        "recent_rain_warmed",
        days=len(series.points),
        start=str(start),
        end=str(end),
    )
