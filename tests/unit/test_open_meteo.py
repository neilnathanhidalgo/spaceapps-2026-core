from __future__ import annotations

from datetime import date

import httpx
import pytest
import respx

from spaceapps_core.clients.open_meteo import OpenMeteoClient
from spaceapps_core.core.errors import InvalidRequestError
from spaceapps_core.schemas.common import Location
from spaceapps_core.schemas.variables import CanonicalVariable


def _fake_om_payload() -> dict:
    return {
        "latitude": -5.19,
        "longitude": -80.63,
        "timezone": "UTC",
        "elevation": 60.0,
        "daily_units": {
            "time": "iso8601",
            "temperature_2m_mean": "°C",
            "temperature_2m_max": "°C",
            "temperature_2m_min": "°C",
            "precipitation_sum": "mm",
            "shortwave_radiation_sum": "MJ/m²",
            "wind_speed_10m_max": "m/s",
        },
        "daily": {
            "time": ["2024-01-01", "2024-01-02", "2024-01-03"],
            "temperature_2m_mean": [25.0, 25.5, None],
            "temperature_2m_max": [30.0, 30.5, 29.5],
            "temperature_2m_min": [20.0, 21.0, 20.5],
            "precipitation_sum": [0.0, 1.2, 5.5],
            "shortwave_radiation_sum": [22.1, 23.0, 20.5],
            "wind_speed_10m_max": [3.0, 3.5, 4.1],
        },
    }


@pytest.mark.asyncio
async def test_open_meteo_forecast_parses() -> None:
    async with respx.mock(assert_all_called=True) as mock:
        route = mock.get("https://api.open-meteo.com/v1/forecast").mock(
            return_value=httpx.Response(200, json=_fake_om_payload())
        )

        client = OpenMeteoClient()
        series = await client.forecast(
            location=Location(lat=-5.19, lon=-80.63),
            forecast_days=3,
            use_cache=False,
        )

    assert route.called
    assert len(series) == 6
    by_var = {s.variable: s for s in series}
    assert by_var[CanonicalVariable.T2M_MEAN].points[2].value is None
    assert by_var[CanonicalVariable.PRECIPITATION].points[2].value == 5.5
    assert by_var[CanonicalVariable.WIND2M].unit == "m/s"


@pytest.mark.asyncio
async def test_open_meteo_rejects_partial_date_range() -> None:
    client = OpenMeteoClient()
    with pytest.raises(InvalidRequestError):
        await client.forecast(
            location=Location(lat=0, lon=0),
            start=date(2024, 1, 1),
            end=None,
            use_cache=False,
        )


@pytest.mark.asyncio
async def test_open_meteo_rejects_out_of_range_forecast_days() -> None:
    client = OpenMeteoClient()
    with pytest.raises(InvalidRequestError):
        await client.forecast(
            location=Location(lat=0, lon=0),
            forecast_days=99,
            use_cache=False,
        )


def test_forecast_router(client) -> None:
    with respx.mock(assert_all_called=True) as mock:
        mock.get("https://api.open-meteo.com/v1/forecast").mock(
            return_value=httpx.Response(200, json=_fake_om_payload())
        )
        r = client.get(
            "/api/v1/climate/forecast",
            params={"lat": -5.19, "lon": -80.63, "forecast_days": 3},
        )
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert any(s["variable"] == "precipitation" for s in data)
