from __future__ import annotations

from typing import Any

from ..core.cache import async_cached_or_set, make_key
from ..core.config import get_settings
from ..core.errors import UpstreamError
from ..core.http import async_client, request_with_retry
from ..schemas.common import Location
from .base import BaseClient

SOILGRIDS_BASE_URL = "https://rest.isric.org/soilgrids/v2.0"
DEFAULT_PROPERTIES = ("sand", "clay", "soc")
DEFAULT_DEPTH = "0-5cm"


class SoilGridsClient(BaseClient):
    """ISRIC SoilGrids v2.0 point query (global soil properties at 250 m).

    Documentation: https://rest.isric.org/soilgrids/v2.0/docs
    No authentication required.

    Unlike the other clients this one does not return a `TimeSeries`: soil
    properties are static, so it returns the mean of each property already
    converted to its target unit (sand/clay in %, organic carbon in g/kg).
    """

    source_name = "soilgrids"

    def __init__(self, *, timeout: float | None = None, base_url: str = SOILGRIDS_BASE_URL) -> None:
        self.timeout = timeout
        self.base_url = base_url

    async def properties_point(
        self,
        location: Location,
        properties: tuple[str, ...] = DEFAULT_PROPERTIES,
        depth: str = DEFAULT_DEPTH,
    ) -> dict[str, float]:
        """Mean value per property, in target units.

        A property the service has no data for (masked pixels: water, bare
        rock, cities) is left out of the result.
        """
        settings = get_settings()
        params: list[tuple[str, Any]] = [
            ("lon", location.lon),
            ("lat", location.lat),
            ("depth", depth),
            ("value", "mean"),
            *(("property", name) for name in properties),
        ]
        cache_key = make_key("soilgrids:properties_point", {"params": params})

        async def fetch() -> dict[str, Any]:
            async with async_client(base_url=self.base_url, timeout=self.timeout) as c:
                r = await request_with_retry(c, "GET", "/properties/query", params=params)
                if r.status_code >= 400:
                    raise UpstreamError(
                        f"SoilGrids returned HTTP {r.status_code}: {r.text[:200]}",
                        details={"status": r.status_code},
                    )
                return r.json()

        data, _ = await async_cached_or_set(cache_key, fetch, settings.cache_ttl_static)
        return parse_properties(data, depth)


def parse_properties(payload: dict[str, Any], depth: str) -> dict[str, float]:
    """Read the SoilGrids response into `{property: value in target unit}`."""
    result: dict[str, float] = {}
    for layer in payload.get("properties", {}).get("layers", []):
        name = layer.get("name")
        factor = layer.get("unit_measure", {}).get("d_factor") or 1
        for sample in layer.get("depths", []):
            if sample.get("label") != depth:
                continue
            mean = sample.get("values", {}).get("mean")
            if name is not None and mean is not None:
                result[name] = mean / factor
    return result
