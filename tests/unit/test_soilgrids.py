from __future__ import annotations

import httpx
import pytest
import respx

from spaceapps_core.clients.soilgrids import (
    SOILGRIDS_BASE_URL,
    SoilGridsClient,
    parse_properties,
)
from spaceapps_core.core.errors import UpstreamError
from spaceapps_core.schemas.common import Location
from spaceapps_core.services.local_soil import (
    carbon_score_shift,
    classify_texture,
    effective_rain_fraction,
    effective_texture,
    fetch_soil_profile,
    soil_profile,
)
from tests.conftest import agro_thresholds as _thresholds

SOILGRIDS_URL = f"{SOILGRIDS_BASE_URL}/properties/query"
PILOT = Location(lat=-5.25, lon=-80.60)


def _layer(name: str, mean: float | None, *, factor: int = 10, label: str = "0-5cm") -> dict:
    return {
        "name": name,
        "unit_measure": {"d_factor": factor},
        "depths": [{"label": label, "values": {"mean": mean}}],
    }


def _payload(sand: float | None = 793, clay: float | None = 70, soc: float | None = 135) -> dict:
    return {
        "properties": {"layers": [_layer("sand", sand), _layer("clay", clay), _layer("soc", soc)]}
    }


def test_parse_properties_applies_the_unit_factor() -> None:
    assert parse_properties(_payload(), "0-5cm") == {
        "sand": 79.3,
        "clay": 7.0,
        "soc": 13.5,
    }


def test_parse_properties_skips_masked_pixels_and_other_depths() -> None:
    assert parse_properties(_payload(sand=None), "0-5cm") == {"clay": 7.0, "soc": 13.5}
    assert parse_properties(_payload(), "5-15cm") == {}


def test_classify_texture() -> None:
    thresholds = _thresholds()

    assert classify_texture(79.3, 7.0, thresholds) == "sandy"
    assert classify_texture(40.0, 20.0, thresholds) == "loamy"
    assert classify_texture(20.0, 45.0, thresholds) == "clayey"
    # La arcilla manda: un suelo con mucha arena y mucha arcilla es arcilloso.
    assert classify_texture(75.0, 40.0, thresholds) == "clayey"


def test_soil_profile_needs_the_three_properties() -> None:
    thresholds = _thresholds()

    profile = soil_profile({"sand": 79.3, "clay": 7.0, "soc": 13.5}, thresholds)

    assert profile is not None
    assert profile.texture == "sandy"
    assert profile.organic_carbon_g_kg == 13.5
    assert profile.depth == "0-5cm"
    assert soil_profile({"sand": 79.3, "clay": 7.0}, thresholds) is None


def test_carbon_score_shift_bands() -> None:
    thresholds = _thresholds()

    def shift(carbon: float) -> int:
        return carbon_score_shift(
            soil_profile({"sand": 50.0, "clay": 20.0, "soc": carbon}, thresholds),
            thresholds,
        )

    assert shift(5.0) == -1
    assert shift(13.5) == 0
    assert shift(25.0) == 1
    assert carbon_score_shift(None, thresholds) == 0


def test_effective_rain_fraction_follows_the_texture() -> None:
    thresholds = _thresholds()

    assert effective_rain_fraction("sandy", thresholds) == 0.6
    # Sin valor para "loamy" se usa la fracción global.
    assert effective_rain_fraction("loamy", thresholds) == 0.8
    assert effective_rain_fraction(None, thresholds) == 0.8


def test_effective_texture_prefers_what_the_farmer_answered() -> None:
    thresholds = _thresholds()
    sandy = soil_profile({"sand": 79.3, "clay": 7.0, "soc": 13.5}, thresholds)

    assert effective_texture(sandy, "clayey") == ("clayey", "farmer")
    assert effective_texture(sandy, None) == ("sandy", "soilgrids")
    assert effective_texture(None, "loamy") == ("loamy", "farmer")
    assert effective_texture(None, None) == (None, None)


async def test_client_reads_the_point() -> None:
    with respx.mock(assert_all_called=True) as mock:
        mock.get(SOILGRIDS_URL).mock(return_value=httpx.Response(200, json=_payload()))
        properties = await SoilGridsClient().properties_point(PILOT)

    assert properties == {"sand": 79.3, "clay": 7.0, "soc": 13.5}


async def test_client_raises_on_upstream_error() -> None:
    with respx.mock(assert_all_called=True) as mock:
        mock.get(SOILGRIDS_URL).mock(return_value=httpx.Response(400, text="bad point"))

        with pytest.raises(UpstreamError):
            await SoilGridsClient().properties_point(PILOT)


async def test_fetch_soil_profile_is_fail_soft() -> None:
    with respx.mock(assert_all_called=True) as mock:
        mock.get(SOILGRIDS_URL).mock(return_value=httpx.Response(400, text="bad point"))

        assert await fetch_soil_profile(PILOT, _thresholds()) is None


async def test_fetch_soil_profile_ignores_a_masked_pixel() -> None:
    with respx.mock(assert_all_called=True) as mock:
        mock.get(SOILGRIDS_URL).mock(
            return_value=httpx.Response(200, json=_payload(sand=None, clay=None, soc=None))
        )

        assert await fetch_soil_profile(PILOT, _thresholds()) is None
