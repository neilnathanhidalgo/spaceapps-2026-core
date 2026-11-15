from __future__ import annotations

from datetime import date

import httpx
import pytest
import respx

from spaceapps_core.clients.ornl_modis import (
    NDVI_BAND,
    NDVI_PRODUCT,
    ORNL_MODIS_BASE_URL,
    OrnlModisClient,
)
from spaceapps_core.core.errors import UpstreamError
from spaceapps_core.schemas.common import Location, TimePoint, TimeSeries
from spaceapps_core.schemas.variables import CanonicalVariable
from spaceapps_core.services.vegetation import (
    annual_means,
    cached_vegetation_trend,
    fetch_vegetation_trend,
    season_windows,
    vegetation_trend,
)

SEASON = (1, 4)

ORNL_URL = f"{ORNL_MODIS_BASE_URL}/{NDVI_PRODUCT}/subset"
PILOT = Location(lat=-5.19, lon=-80.63)


def _subset(values: dict[str, int]) -> dict:
    return {
        "scale": "0.0001",
        "band": NDVI_BAND,
        "subset": [
            {"calendar_date": day, "band": NDVI_BAND, "data": [value]}
            for day, value in values.items()
        ],
    }


def _series(values: dict[str, float | None]) -> TimeSeries:
    return TimeSeries(
        source="ornl_modis",
        variable=CanonicalVariable.NDVI,
        unit="index",
        location=PILOT,
        points=[
            TimePoint(date=date.fromisoformat(day), value=value) for day, value in values.items()
        ],
    )


def test_client_scales_values_and_drops_fill_values() -> None:
    payload = _subset({"2023-01-01": 786, "2023-01-17": 1433, "2023-02-02": -3000})

    series = OrnlModisClient()._parse_subset(payload, PILOT, NDVI_PRODUCT, NDVI_BAND)

    assert series.variable is CanonicalVariable.NDVI
    assert [(p.date.isoformat(), p.value) for p in series.points] == [
        ("2023-01-01", pytest.approx(0.0786)),
        ("2023-01-17", pytest.approx(0.1433)),
        ("2023-02-02", None),
    ]


def test_annual_means_skips_missing_composites() -> None:
    series = _series({"2021-01-01": 0.4, "2021-07-01": 0.6, "2022-01-01": None, "2022-07-01": 0.3})

    assert annual_means(series) == {2021: pytest.approx(0.5), 2022: pytest.approx(0.3)}


def test_vegetation_trend_directions() -> None:
    def trend(start: float, end: float):
        series = _series({"2021-01-01": start, "2026-01-01": end})
        return vegetation_trend(series, flat_tolerance=0.05)

    falling = trend(0.5, 0.4)
    assert falling is not None
    assert falling.direction == "down"
    assert falling.change_ratio == pytest.approx(-0.2)
    assert falling.start_year == 2021
    assert falling.end_year == 2026

    assert trend(0.5, 0.51).direction == "flat"
    assert trend(0.4, 0.5).direction == "up"


def test_vegetation_trend_needs_two_usable_years() -> None:
    assert vegetation_trend(_series({"2021-01-01": 0.4}), flat_tolerance=0.05) is None
    assert (
        vegetation_trend(_series({"2021-01-01": 0.0, "2026-01-01": 0.4}), flat_tolerance=0.05)
        is None
    )


async def test_client_requests_the_window_in_modis_dates() -> None:
    with respx.mock(assert_all_called=True) as mock:
        route = mock.get(ORNL_URL).mock(
            return_value=httpx.Response(200, json=_subset({"2023-01-01": 786}))
        )
        await OrnlModisClient().ndvi_point(PILOT, start=date(2023, 1, 1), end=date(2023, 12, 31))

    params = route.calls.last.request.url.params
    assert params["startDate"] == "A2023001"
    assert params["endDate"] == "A2023365"
    assert params["band"] == NDVI_BAND


async def test_client_raises_on_upstream_error() -> None:
    with respx.mock(assert_all_called=True) as mock:
        mock.get(ORNL_URL).mock(return_value=httpx.Response(400, text="bad product"))

        with pytest.raises(UpstreamError):
            await OrnlModisClient().ndvi_point(PILOT, start=date(2023, 1, 1), end=date(2023, 2, 1))


def test_season_windows_covers_only_the_first_and_the_last_year() -> None:
    windows = season_windows(years=5, season=SEASON, today=date(2026, 11, 14))

    assert windows == [
        (date(2021, 1, 1), date(2021, 4, 30)),
        (date(2026, 1, 1), date(2026, 4, 30)),
    ]


def test_season_windows_cuts_the_window_at_today() -> None:
    windows = season_windows(years=5, season=SEASON, today=date(2026, 2, 10))

    assert windows[-1] == (date(2026, 1, 1), date(2026, 2, 10))


async def test_fetch_vegetation_trend_is_fail_soft() -> None:
    with respx.mock(assert_all_called=True) as mock:
        mock.get(ORNL_URL).mock(return_value=httpx.Response(400, text="bad product"))

        trend = await fetch_vegetation_trend(
            PILOT,
            years=5,
            flat_tolerance=0.05,
            season=SEASON,
            today=date(2026, 11, 14),
        )

    assert trend is None


async def test_cached_trend_needs_both_windows_in_the_cache() -> None:
    def subset(request: httpx.Request) -> httpx.Response:
        year = request.url.params["startDate"][1:5]
        value = 5000 if year == "2021" else 4000
        return httpx.Response(200, json=_subset({f"{year}-02-01": value}))

    def cached():
        return cached_vegetation_trend(
            PILOT,
            years=5,
            flat_tolerance=0.05,
            season=SEASON,
            today=date(2026, 11, 14),
        )

    assert cached() is None

    with respx.mock(assert_all_called=True) as mock:
        mock.get(ORNL_URL).mock(side_effect=subset)
        await fetch_vegetation_trend(
            PILOT,
            years=5,
            flat_tolerance=0.05,
            season=SEASON,
            today=date(2026, 11, 14),
        )

    trend = cached()
    assert trend is not None
    assert trend.direction == "down"


async def test_fetch_vegetation_trend_asks_only_for_the_two_years() -> None:
    def subset(request: httpx.Request) -> httpx.Response:
        year = request.url.params["startDate"][1:5]
        value = 5000 if year == "2021" else 4000
        return httpx.Response(200, json=_subset({f"{year}-02-01": value}))

    with respx.mock(assert_all_called=True) as mock:
        route = mock.get(ORNL_URL).mock(side_effect=subset)
        trend = await fetch_vegetation_trend(
            PILOT,
            years=5,
            flat_tolerance=0.05,
            season=SEASON,
            today=date(2026, 11, 14),
        )

    windows = {call.request.url.params["startDate"] for call in route.calls}
    assert windows == {"A2021001", "A2026001"}
    assert trend is not None
    assert trend.direction == "down"
    assert trend.start_year == 2021
    assert trend.end_year == 2026
    assert trend.change_ratio == pytest.approx(-0.2)
