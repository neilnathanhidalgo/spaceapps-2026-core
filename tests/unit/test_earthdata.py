from __future__ import annotations

from datetime import date

import pytest

from spaceapps_core.clients.earthdata import EarthdataClient
from spaceapps_core.core.errors import NotConfiguredError
from spaceapps_core.schemas.common import Location
from spaceapps_core.schemas.variables import CanonicalVariable


@pytest.fixture
def earthdata_env(monkeypatch) -> None:
    monkeypatch.setenv("EARTHDATA_USERNAME", "demo-user")
    monkeypatch.setenv("EARTHDATA_PASSWORD", "demo-pass")
    from spaceapps_core.core.config import get_settings

    get_settings.cache_clear()
    EarthdataClient._logged_in = False
    yield
    get_settings.cache_clear()
    EarthdataClient._logged_in = False


@pytest.fixture
def no_earthdata_env(monkeypatch) -> None:
    monkeypatch.delenv("EARTHDATA_USERNAME", raising=False)
    monkeypatch.delenv("EARTHDATA_PASSWORD", raising=False)
    from spaceapps_core.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_imerg_requires_credentials(no_earthdata_env) -> None:
    with pytest.raises(NotConfiguredError):
        await EarthdataClient().imerg_daily_point(
            location=Location(lat=0, lon=0),
            start=date(2024, 1, 1),
            end=date(2024, 1, 2),
        )


@pytest.mark.asyncio
async def test_imerg_daily_point_pipeline(earthdata_env, monkeypatch) -> None:
    monkeypatch.setattr(
        "spaceapps_core.clients.earthdata.EarthdataClient._login",
        lambda self: None,
    )

    sample = [
        {"date": "2024-01-01", "value": 0.0},
        {"date": "2024-01-02", "value": 1.5},
        {"date": "2024-01-03", "value": None},
    ]

    def fake_sync(self, *, location, start, end):
        return sample

    monkeypatch.setattr(
        "spaceapps_core.clients.earthdata.EarthdataClient._imerg_daily_sync",
        fake_sync,
    )

    series = await EarthdataClient().imerg_daily_point(
        location=Location(lat=-5.19, lon=-80.63),
        start=date(2024, 1, 1),
        end=date(2024, 1, 3),
    )

    assert series.variable == CanonicalVariable.PRECIPITATION
    assert series.unit == "mm/day"
    assert [p.date.isoformat() for p in series.points] == [
        "2024-01-01",
        "2024-01-02",
        "2024-01-03",
    ]
    assert series.points[2].value is None


def test_precipitation_route(client, earthdata_env, monkeypatch) -> None:
    monkeypatch.setattr(
        "spaceapps_core.clients.earthdata.EarthdataClient._login",
        lambda self: None,
    )

    def fake_sync(self, *, location, start, end):
        return [{"date": "2024-01-01", "value": 2.5}]

    monkeypatch.setattr(
        "spaceapps_core.clients.earthdata.EarthdataClient._imerg_daily_sync",
        fake_sync,
    )

    r = client.get(
        "/api/v1/precipitation",
        params={
            "lat": -5.19,
            "lon": -80.63,
            "start": "2024-01-01",
            "end": "2024-01-01",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["variable"] == "precipitation"
    assert body["points"][0]["value"] == 2.5
