from __future__ import annotations

from datetime import date, datetime
from typing import Any

from ..core.cache import async_cached_or_set, make_key, peek
from ..core.config import get_settings
from ..core.errors import UpstreamError
from ..core.http import async_client, request_with_retry
from ..schemas.common import Location, TimePoint, TimeSeries
from ..schemas.variables import CANONICAL_VARIABLES, CanonicalVariable
from .base import BaseClient

ORNL_MODIS_BASE_URL = "https://modis.ornl.gov/rst/api/v1"
NDVI_PRODUCT = "MOD13Q1"
NDVI_BAND = "250m_16_days_NDVI"
NDVI_VALID_MIN = -2000
NDVI_VALID_MAX = 10000


class OrnlModisClient(BaseClient):
    """MODIS/VIIRS point subsets from the ORNL DAAC REST service.

    Documentation: https://modis.ornl.gov/rst/ui/
    No authentication required, unlike the AppEEARS flow: it answers
    synchronously for a single point, which is what the recommendation needs.
    """

    source_name = "ornl_modis"

    def __init__(
        self,
        *,
        timeout: float | None = None,
        base_url: str = ORNL_MODIS_BASE_URL,
    ) -> None:
        self.timeout = timeout
        self.base_url = base_url

    @staticmethod
    def _params(location: Location, start: date, end: date, band: str) -> dict[str, Any]:
        return {
            "latitude": location.lat,
            "longitude": location.lon,
            "startDate": _modis_date(start),
            "endDate": _modis_date(end),
            "band": band,
            "kmAboveBelow": 0,
            "kmLeftRight": 0,
        }

    def cache_key(
        self,
        location: Location,
        start: date,
        end: date,
        *,
        product: str = NDVI_PRODUCT,
        band: str = NDVI_BAND,
    ) -> str:
        """Key under which `ndvi_point` stores this window."""
        return make_key(f"ornl_modis:{product}:{band}", self._params(location, start, end, band))

    def cached_ndvi_point(
        self,
        location: Location,
        start: date,
        end: date,
        *,
        product: str = NDVI_PRODUCT,
        band: str = NDVI_BAND,
    ) -> TimeSeries | None:
        """The window if it is already cached, without contacting the service."""
        payload = peek(self.cache_key(location, start, end, product=product, band=band))
        if payload is None:
            return None
        return self._parse_subset(payload, location, product, band)

    async def ndvi_point(
        self,
        location: Location,
        start: date,
        end: date,
        *,
        product: str = NDVI_PRODUCT,
        band: str = NDVI_BAND,
    ) -> TimeSeries:
        """16-day NDVI composites at the point, scaled to -1..1."""
        settings = get_settings()
        params = self._params(location, start, end, band)
        cache_key = make_key(f"ornl_modis:{product}:{band}", params)

        async def fetch() -> dict[str, Any]:
            async with async_client(base_url=self.base_url, timeout=self.timeout) as c:
                r = await request_with_retry(
                    c,
                    "GET",
                    f"/{product}/subset",
                    params=params,
                    headers={"Accept": "application/json"},
                )
                if r.status_code >= 400:
                    raise UpstreamError(
                        f"ORNL MODIS returned HTTP {r.status_code}: {r.text[:200]}",
                        details={"status": r.status_code},
                    )
                return r.json()

        data, _ = await async_cached_or_set(cache_key, fetch, settings.cache_ttl_history)
        return self._parse_subset(data, location, product, band)

    def _parse_subset(
        self,
        payload: dict[str, Any],
        location: Location,
        product: str,
        band: str,
    ) -> TimeSeries:
        scale = _float_or_one(payload.get("scale"))
        points: list[TimePoint] = []
        for entry in payload.get("subset", []):
            parsed = _parse_calendar_date(entry.get("calendar_date"))
            values = entry.get("data") or []
            if parsed is None or not values:
                continue
            raw = values[0]
            valid = raw is not None and NDVI_VALID_MIN <= raw <= NDVI_VALID_MAX
            points.append(TimePoint(date=parsed, value=raw * scale if valid else None))

        points.sort(key=lambda p: p.date)
        return TimeSeries(
            source=self.source_name,
            variable=CanonicalVariable.NDVI,
            unit=CANONICAL_VARIABLES[CanonicalVariable.NDVI].unit,
            location=location,
            temporal_resolution="daily",
            points=points,
            metadata={
                "product": product,
                "band": band,
                "api": "ornl_modis_rest",
                "scale": scale,
            },
        )


def _modis_date(day: date) -> str:
    """ORNL expects `AYYYYDDD` (year plus day of the year)."""
    return f"A{day.year}{day.timetuple().tm_yday:03d}"


def _parse_calendar_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _float_or_one(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 1.0
