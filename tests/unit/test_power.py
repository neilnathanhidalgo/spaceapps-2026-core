from __future__ import annotations

from datetime import date

import httpx
import pytest
import respx

from spaceapps_core.clients.power import PowerClient
from spaceapps_core.schemas.common import Location
from spaceapps_core.schemas.variables import CanonicalVariable


def _fake_power_payload() -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [-80.63, -5.19, 10.0]},
        "properties": {
            "parameter": {
                "T2M": {"20240101": 25.3, "20240102": 25.6, "20240103": -999.0},
                "PRECTOTCORR": {"20240101": 0.0, "20240102": 2.5, "20240103": 1.2},
            }
        },
        "header": {"title": "NASA/POWER Source Native Resolution Daily Data"},
        "parameters": {
            "T2M": {"units": "C"},
            "PRECTOTCORR": {"units": "mm/day"},
        },
    }


@pytest.mark.asyncio
async def test_power_daily_point_parses_payload() -> None:
    async with respx.mock(assert_all_called=True) as mock:
        route = mock.get("https://power.larc.nasa.gov/api/temporal/daily/point").mock(
            return_value=httpx.Response(200, json=_fake_power_payload())
        )

        client = PowerClient()
        series = await client.daily_point(
            location=Location(lat=-5.19, lon=-80.63),
            start=date(2024, 1, 1),
            end=date(2024, 1, 3),
            variables=[CanonicalVariable.T2M_MEAN, CanonicalVariable.PRECIPITATION],
            use_cache=False,
        )

    assert route.called
    assert len(series) == 2
    by_var = {s.variable: s for s in series}
    t2m = by_var[CanonicalVariable.T2M_MEAN]
    assert t2m.unit == "degC"
    assert len(t2m.points) == 3
    assert t2m.points[0].date == date(2024, 1, 1)
    assert t2m.points[0].value == 25.3
    assert t2m.points[2].value is None
    assert t2m.metadata["source_variable"] == "T2M"
    assert t2m.metadata["api"] == "nasa_power"


@pytest.mark.asyncio
async def test_power_daily_point_upstream_error_bubbles() -> None:
    async with respx.mock(assert_all_called=True) as mock:
        mock.get("https://power.larc.nasa.gov/api/temporal/daily/point").mock(
            return_value=httpx.Response(400, text="bad request")
        )

        client = PowerClient()
        with pytest.raises(Exception) as exc_info:
            await client.daily_point(
                location=Location(lat=0.0, lon=0.0),
                start=date(2024, 1, 1),
                end=date(2024, 1, 2),
                variables=[CanonicalVariable.T2M_MEAN],
                use_cache=False,
            )
        assert "400" in str(exc_info.value)


@pytest.mark.asyncio
async def test_power_timeout_wraps_to_upstream_timeout() -> None:
    from spaceapps_core.core.errors import UpstreamTimeout

    async with respx.mock(assert_all_called=True) as mock:
        mock.get("https://power.larc.nasa.gov/api/temporal/daily/point").mock(
            side_effect=httpx.TimeoutException("boom")
        )

        client = PowerClient()
        with pytest.raises(UpstreamTimeout):
            await client.daily_point(
                location=Location(lat=0.0, lon=0.0),
                start=date(2024, 1, 1),
                end=date(2024, 1, 2),
                variables=[CanonicalVariable.T2M_MEAN],
                use_cache=False,
            )


def test_power_router_returns_json(client) -> None:
    with respx.mock(assert_all_called=True) as mock:
        mock.get("https://power.larc.nasa.gov/api/temporal/daily/point").mock(
            return_value=httpx.Response(200, json=_fake_power_payload())
        )

        r = client.get(
            "/api/v1/climate/history",
            params={
                "lat": -5.19,
                "lon": -80.63,
                "start": "2024-01-01",
                "end": "2024-01-03",
                "variables": ["t2m_mean", "precipitation"],
            },
        )
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert {s["variable"] for s in data} == {"t2m_mean", "precipitation"}


def test_power_router_csv_format(client) -> None:
    with respx.mock(assert_all_called=True) as mock:
        mock.get("https://power.larc.nasa.gov/api/temporal/daily/point").mock(
            return_value=httpx.Response(200, json=_fake_power_payload())
        )

        r = client.get(
            "/api/v1/climate/history",
            params={
                "lat": -5.19,
                "lon": -80.63,
                "start": "2024-01-01",
                "end": "2024-01-03",
                "format": "csv",
                "variables": ["t2m_mean"],
            },
        )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "date,value,variable,unit,source,lat,lon" in r.text


def test_power_router_rejects_bad_date_range(client) -> None:
    r = client.get(
        "/api/v1/climate/history",
        params={
            "lat": -5.19,
            "lon": -80.63,
            "start": "2024-01-10",
            "end": "2024-01-01",
        },
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "http_error"
