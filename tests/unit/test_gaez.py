from __future__ import annotations

import httpx
import pytest
import respx

from spaceapps_core.clients.gaez import GAEZ_IMAGE_SERVER_URL, GaezClient
from spaceapps_core.core.errors import InvalidRequestError
from spaceapps_core.schemas.common import Location

_CATALOG = {
    "features": [
        {"attributes": {"objectid": 1, "crop": "Maize"}},
        {"attributes": {"objectid": 2, "crop": "Wheat"}},
        {"attributes": {"objectid": 3, "crop": "Cotton"}},
    ]
}
_VALUES = {1: "1917", 2: "2788", 3: "NoData"}


def _samples(request: httpx.Request) -> httpx.Response:
    import json

    raster_id = json.loads(request.url.params["mosaicRule"])["lockRasterIds"][0]
    return httpx.Response(200, json={"samples": [{"value": _VALUES[raster_id]}]})


@pytest.mark.asyncio
async def test_crop_suitability_sorted_and_scaled() -> None:
    async with respx.mock(assert_all_called=True) as mock:
        mock.get(f"{GAEZ_IMAGE_SERVER_URL}/query").mock(
            return_value=httpx.Response(200, json=_CATALOG)
        )
        mock.get(f"{GAEZ_IMAGE_SERVER_URL}/getSamples").mock(side_effect=_samples)

        report = await GaezClient().crop_suitability(
            Location(lat=-5.24, lon=-79.45), crops=["cotton", "maize", "wheat"]
        )

    assert [c.crop for c in report.crops] == ["Wheat", "Maize", "Cotton"]
    assert report.crops[0].suitability_index == 0.2788
    assert report.crops[2].suitability_index is None
    assert report.period == "1981-2010"


@pytest.mark.asyncio
async def test_crop_suitability_rejects_unknown_crop() -> None:
    async with respx.mock() as mock:
        mock.get(f"{GAEZ_IMAGE_SERVER_URL}/query").mock(
            return_value=httpx.Response(200, json=_CATALOG)
        )
        with pytest.raises(InvalidRequestError):
            await GaezClient().crop_suitability(Location(lat=0, lon=0), crops=["Quinoa"])
