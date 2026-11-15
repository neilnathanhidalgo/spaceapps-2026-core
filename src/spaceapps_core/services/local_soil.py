"""Local soil properties under the plot (SoilGrids and the farmer).

Pure classification plus one fail-soft fetch: if SoilGrids has no data for
the point (water, rock or urban masks return nulls), the recommendation goes
on without it instead of failing.

The texture can also come from the farmer: the app shows the three textures
and asks "does your soil look like this one?". That answer wins over
SoilGrids, which averages 250 m around the plot.
"""

from __future__ import annotations

from ..clients.soilgrids import DEFAULT_DEPTH, SoilGridsClient
from ..core.errors import SpaceAppsError
from ..core.logging import get_logger
from ..schemas.common import Location
from ..schemas.recommendation import SoilProfile, SoilTexture, SoilTextureSource
from .agro_config import ThresholdsConfig

log = get_logger(__name__)


def classify_texture(
    sand_percent: float,
    clay_percent: float,
    thresholds: ThresholdsConfig,
) -> SoilTexture:
    """Coarse texture class: what changes how much rain the crop can use."""
    if clay_percent >= thresholds.clayey_clay_percent:
        return "clayey"
    if sand_percent >= thresholds.sandy_sand_percent:
        return "sandy"
    return "loamy"


def soil_profile(
    properties: dict[str, float],
    thresholds: ThresholdsConfig,
    *,
    depth: str = DEFAULT_DEPTH,
) -> SoilProfile | None:
    """Build the profile from a SoilGrids reading, or `None` if incomplete."""
    sand, clay, carbon = (properties.get(k) for k in ("sand", "clay", "soc"))
    if sand is None or clay is None or carbon is None:
        return None
    return SoilProfile(
        sand_percent=round(sand, 1),
        clay_percent=round(clay, 1),
        organic_carbon_g_kg=round(carbon, 1),
        texture=classify_texture(sand, clay, thresholds),
        depth=depth,
    )


def carbon_score_shift(profile: SoilProfile | None, thresholds: ThresholdsConfig) -> int:
    """How much the organic carbon moves the starting soil score."""
    if profile is None:
        return 0
    if profile.organic_carbon_g_kg < thresholds.soil_organic_carbon_low_g_kg:
        return -1
    if profile.organic_carbon_g_kg >= thresholds.soil_organic_carbon_high_g_kg:
        return 1
    return 0


def effective_texture(
    profile: SoilProfile | None,
    reported: SoilTexture | None,
) -> tuple[SoilTexture | None, SoilTextureSource | None]:
    """Texture the water balance uses, and who said so.

    The farmer's answer wins: they have the soil in their hand.
    """
    if reported is not None:
        return reported, "farmer"
    if profile is not None:
        return profile.texture, "soilgrids"
    return None, None


def effective_rain_fraction(
    texture: SoilTexture | None,
    thresholds: ThresholdsConfig,
) -> float:
    """Share of rainfall the crop can use, by texture when it is known."""
    if texture is None:
        return thresholds.effective_rain_fraction
    by_texture = thresholds.effective_rain_fraction_by_texture
    return by_texture.get(texture, thresholds.effective_rain_fraction)


async def fetch_soil_profile(
    location: Location,
    thresholds: ThresholdsConfig,
) -> SoilProfile | None:
    """Read SoilGrids for the point. Returns `None` if it has nothing usable."""
    try:
        properties = await SoilGridsClient().properties_point(location)
    except SpaceAppsError as error:
        log.warning("soilgrids_unavailable", error=error.message)
        return None
    return soil_profile(properties, thresholds)
