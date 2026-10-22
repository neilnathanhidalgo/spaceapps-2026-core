from __future__ import annotations

from datetime import date

import httpx
import pytest
import respx

from spaceapps_core.clients.copernicus import CopernicusClient
from spaceapps_core.schemas.common import Location


def _fake_stac_response() -> dict:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "id": "S2A_MSIL2A_20240101T152651_R125_T17MMU_20240101T200456",
                "collection": "SENTINEL-2",
                "properties": {
                    "datetime": "2024-01-01T15:26:51Z",
                    "eo:cloud_cover": 12.3,
                    "platform": "sentinel-2a",
                },
                "assets": {"B04": {"href": "..."}, "B08": {"href": "..."}},
                "links": [
                    {
                        "rel": "self",
                        "href": "https://example/stac/items/XYZ",
                    }
                ],
            }
        ],
    }


@pytest.mark.asyncio
async def test_sentinel2_search_parses() -> None:
    async with respx.mock(assert_all_called=True) as mock:
        mock.post("https://catalogue.dataspace.copernicus.eu/stac/search").mock(
            return_value=httpx.Response(200, json=_fake_stac_response())
        )

        scenes = await CopernicusClient().search_sentinel2(
            location=Location(lat=-5.19, lon=-80.63),
            start=date(2024, 1, 1),
            end=date(2024, 1, 31),
        )

    assert len(scenes) == 1
    assert scenes[0]["cloud_cover"] == 12.3
    assert "B04" in scenes[0]["assets"]
    assert scenes[0]["self_href"].startswith("https://example")


def test_sentinel2_router(client) -> None:
    with respx.mock(assert_all_called=True) as mock:
        mock.post("https://catalogue.dataspace.copernicus.eu/stac/search").mock(
            return_value=httpx.Response(200, json=_fake_stac_response())
        )

        r = client.get(
            "/api/v1/sentinel-2/scenes",
            params={
                "lat": -5.19,
                "lon": -80.63,
                "start": "2024-01-01",
                "end": "2024-01-31",
            },
        )
    assert r.status_code == 200
    assert r.json()[0]["id"].startswith("S2A_")
