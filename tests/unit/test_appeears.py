from __future__ import annotations

import os
from datetime import date

import httpx
import pytest
import respx

from spaceapps_core.clients.appeears import (
    HLS_NDVI_LAYERS,
    MODIS_NDVI_LAYERS,
    AppEEARSClient,
)
from spaceapps_core.core.errors import NotConfiguredError
from spaceapps_core.schemas.common import Location
from spaceapps_core.schemas.variables import CanonicalVariable


@pytest.fixture
def earthdata_env(monkeypatch) -> None:
    monkeypatch.setenv("EARTHDATA_USERNAME", "demo-user")
    monkeypatch.setenv("EARTHDATA_PASSWORD", "demo-pass")
    from spaceapps_core.clients.appeears import TOKEN_CACHE_KEY
    from spaceapps_core.core.cache import get_cache
    from spaceapps_core.core.config import get_settings

    get_settings.cache_clear()
    get_cache().delete(TOKEN_CACHE_KEY)
    yield
    get_settings.cache_clear()
    get_cache().delete(TOKEN_CACHE_KEY)


@pytest.fixture
def no_earthdata_env(monkeypatch) -> None:
    monkeypatch.delenv("EARTHDATA_USERNAME", raising=False)
    monkeypatch.delenv("EARTHDATA_PASSWORD", raising=False)
    from spaceapps_core.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_login_requires_credentials(no_earthdata_env) -> None:
    client = AppEEARSClient()
    with pytest.raises(NotConfiguredError):
        await client.login(force=True)


@pytest.mark.asyncio
async def test_submit_point_task_round_trip(earthdata_env) -> None:
    async with respx.mock(assert_all_called=True) as mock:
        mock.post("https://appeears.earthdatacloud.nasa.gov/api/login").mock(
            return_value=httpx.Response(200, json={"token": "tok-123"})
        )
        task_route = mock.post("https://appeears.earthdatacloud.nasa.gov/api/task").mock(
            return_value=httpx.Response(200, json={"task_id": "task-abc"})
        )

        client = AppEEARSClient()
        task_id = await client.submit_point_task(
            location=Location(lat=-5.19, lon=-80.63),
            start=date(2024, 1, 1),
            end=date(2024, 1, 31),
            layers=MODIS_NDVI_LAYERS,
        )

    assert task_id == "task-abc"
    import json

    body = json.loads(task_route.calls[0].request.content)
    assert body["task_type"] == "point"
    assert body["params"]["dates"][0]["startDate"] == "01-01-2024"
    assert body["params"]["dates"][0]["endDate"] == "01-31-2024"


def test_parse_point_csv() -> None:
    csv_bytes = (
        b"ID,Latitude,Longitude,Date,MOD13Q1_061__250m_16_days_NDVI,MOD13Q1_061__250m_16_days_EVI\n"
        b"0,-5.19,-80.63,2024-01-01,0.6,0.55\n"
        b"0,-5.19,-80.63,2024-01-17,,0.5\n"
        b"0,-5.19,-80.63,2024-02-02,0.7,0.6\n"
    )
    series = AppEEARSClient.parse_point_csv(
        csv_bytes,
        MODIS_NDVI_LAYERS,
        Location(lat=-5.19, lon=-80.63),
    )
    assert len(series) == 2
    ndvi = next(s for s in series if s.variable == CanonicalVariable.NDVI)
    assert len(ndvi.points) == 3
    assert ndvi.points[0].value == 0.6
    assert ndvi.points[1].value is None
    assert ndvi.metadata["product"] == "MOD13Q1.061"


def test_vegetation_route_submits_job(client, earthdata_env, monkeypatch) -> None:
    # ensure the cache fixture doesn't carry a token across tests
    os.environ.pop("APPEEARS_TOKEN", None)
    with respx.mock(assert_all_called=True) as mock:
        mock.post("https://appeears.earthdatacloud.nasa.gov/api/login").mock(
            return_value=httpx.Response(200, json={"token": "tok"})
        )
        mock.post("https://appeears.earthdatacloud.nasa.gov/api/task").mock(
            return_value=httpx.Response(200, json={"task_id": "job-xyz"})
        )

        r = client.post(
            "/api/v1/vegetation/jobs",
            params={
                "lat": -5.19,
                "lon": -80.63,
                "start": "2024-01-01",
                "end": "2024-01-31",
            },
        )
    assert r.status_code == 200
    body = r.json()
    assert body["job_id"] == "job-xyz"
    assert body["source"] == "appeears_modis"


def test_parse_point_csv_only_returns_layers_present_in_file() -> None:
    csv_bytes = b"ID,Latitude,Longitude,Date,HLSS30_VI_020_NDVI\n0,-5.19,-80.63,2024-01-05,0.42\n"
    series = AppEEARSClient.parse_point_csv(
        csv_bytes, HLS_NDVI_LAYERS, Location(lat=-5.19, lon=-80.63)
    )
    assert len(series) == 1
    assert series[0].metadata["product"] == "HLSS30_VI.020"
    assert series[0].points[0].value == 0.42


def test_parse_point_csv_ignores_lookup_tables() -> None:
    csv_bytes = b"Value,MODLAND,VI Usefulness\n2112,0b00,0b0001\n"
    series = AppEEARSClient.parse_point_csv(
        csv_bytes, MODIS_NDVI_LAYERS, Location(lat=-5.19, lon=-80.63)
    )
    assert series == []


def test_vegetation_route_hls_sensor(client, earthdata_env) -> None:
    with respx.mock(assert_all_called=True) as mock:
        mock.post("https://appeears.earthdatacloud.nasa.gov/api/login").mock(
            return_value=httpx.Response(200, json={"token": "tok"})
        )
        task_route = mock.post("https://appeears.earthdatacloud.nasa.gov/api/task").mock(
            return_value=httpx.Response(200, json={"task_id": "job-hls"})
        )

        r = client.post(
            "/api/v1/vegetation/jobs",
            params={
                "lat": -5.19,
                "lon": -80.63,
                "start": "2024-01-01",
                "end": "2024-01-31",
                "sensor": "hls",
            },
        )

    assert r.status_code == 200
    assert r.json()["source"] == "appeears_hls"
    import json

    layers = json.loads(task_route.calls[0].request.content)["params"]["layers"]
    assert {layer["product"] for layer in layers} == {"HLSL30_VI.020", "HLSS30_VI.020"}


def test_terrain_route_uses_srtm_acquisition_dates(client, earthdata_env) -> None:
    with respx.mock(assert_all_called=True) as mock:
        mock.post("https://appeears.earthdatacloud.nasa.gov/api/login").mock(
            return_value=httpx.Response(200, json={"token": "tok"})
        )
        task_route = mock.post("https://appeears.earthdatacloud.nasa.gov/api/task").mock(
            return_value=httpx.Response(200, json={"task_id": "job-srtm"})
        )

        r = client.post("/api/v1/terrain/jobs", params={"lat": -5.19, "lon": -80.63})

    assert r.status_code == 200
    import json

    dates = json.loads(task_route.calls[0].request.content)["params"]["dates"][0]
    assert dates == {"startDate": "02-11-2000", "endDate": "02-21-2000"}
