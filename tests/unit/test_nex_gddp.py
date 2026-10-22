from __future__ import annotations

from datetime import date

import pytest

from spaceapps_core.clients.nex_gddp import NexGddpClient, _convert
from spaceapps_core.core.errors import InvalidRequestError
from spaceapps_core.schemas.common import Location
from spaceapps_core.schemas.variables import CanonicalVariable


def test_convert_units() -> None:
    assert _convert("pr", 0.001) == pytest.approx(86.4)
    assert _convert("tas", 300.15) == pytest.approx(27.0)
    assert _convert("tasmax", 310.15) == pytest.approx(37.0)


@pytest.mark.asyncio
async def test_projections_rejects_bad_scenario() -> None:
    with pytest.raises(InvalidRequestError):
        await NexGddpClient().projections_point(
            location=Location(lat=0, lon=0),
            start=date(2020, 1, 1),
            end=date(2020, 1, 2),
            scenario="not-a-scenario",
        )


@pytest.mark.asyncio
async def test_projections_point_pipeline(monkeypatch) -> None:
    def fake_sync(self, *, variable_cmip, scenario, start, end, location):
        if variable_cmip == "pr":
            return [
                {"date": "2015-01-01", "value": 0.0},
                {"date": "2015-01-02", "value": 3.2},
            ]
        return [
            {"date": "2015-01-01", "value": 25.0},
            {"date": "2015-01-02", "value": 25.5},
        ]

    monkeypatch.setattr(
        "spaceapps_core.clients.nex_gddp.NexGddpClient._fetch_variable_sync",
        fake_sync,
    )

    series = await NexGddpClient().projections_point(
        location=Location(lat=-5.19, lon=-80.63),
        start=date(2015, 1, 1),
        end=date(2015, 1, 2),
        scenario="ssp245",
        variables=[CanonicalVariable.PRECIPITATION, CanonicalVariable.T2M_MEAN],
    )

    assert len(series) == 2
    by_var = {s.variable: s for s in series}
    assert by_var[CanonicalVariable.PRECIPITATION].unit == "mm/day"
    assert by_var[CanonicalVariable.T2M_MEAN].points[1].value == 25.5
    assert by_var[CanonicalVariable.T2M_MEAN].metadata["scenario"] == "ssp245"


def test_projections_route(client, monkeypatch) -> None:
    def fake_sync(self, *, variable_cmip, scenario, start, end, location):
        return [{"date": "2020-01-01", "value": 1.0}]

    monkeypatch.setattr(
        "spaceapps_core.clients.nex_gddp.NexGddpClient._fetch_variable_sync",
        fake_sync,
    )

    r = client.get(
        "/api/v1/projections",
        params={
            "lat": -5.19,
            "lon": -80.63,
            "start": "2020-01-01",
            "end": "2020-01-01",
            "variables": ["precipitation"],
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data[0]["variable"] == "precipitation"
    assert data[0]["points"][0]["value"] == 1.0
