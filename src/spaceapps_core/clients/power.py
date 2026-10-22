from __future__ import annotations

from datetime import date, datetime
from typing import Any

import httpx

from ..core.cache import async_cached_or_set, make_key
from ..core.config import get_settings
from ..core.errors import UpstreamError
from ..core.http import async_client, request_with_retry
from ..schemas.common import Location, TimePoint, TimeSeries
from ..schemas.variables import CANONICAL_VARIABLES, CanonicalVariable
from .base import BaseClient

POWER_BASE_URL = "https://power.larc.nasa.gov/api"
POWER_MISSING = -999.0

DEFAULT_PARAMETERS: list[CanonicalVariable] = [
    CanonicalVariable.T2M_MEAN,
    CanonicalVariable.T2M_MAX,
    CanonicalVariable.T2M_MIN,
    CanonicalVariable.PRECIPITATION,
    CanonicalVariable.RH2M,
    CanonicalVariable.SOLAR_RADIATION,
    CanonicalVariable.WIND2M,
]


def _canonical_to_power(variable: CanonicalVariable) -> str:
    alias = CANONICAL_VARIABLES[variable].source_aliases.get("power")
    if alias is None:
        raise ValueError(f"POWER has no alias for canonical variable {variable}.")
    return alias


def _power_to_canonical(power_name: str) -> CanonicalVariable | None:
    for canonical, spec in CANONICAL_VARIABLES.items():
        if spec.source_aliases.get("power") == power_name:
            return canonical
    return None


class PowerClient(BaseClient):
    """NASA POWER agroclimatology client (community=ag).

    Documentation: https://power.larc.nasa.gov/docs/services/api/
    No authentication required.
    """

    source_name = "power"

    def __init__(
        self,
        *,
        community: str = "ag",
        timeout: float | None = None,
        base_url: str = POWER_BASE_URL,
    ) -> None:
        self.community = community
        self.timeout = timeout
        self.base_url = base_url

    async def daily_point(
        self,
        location: Location,
        start: date,
        end: date,
        variables: list[CanonicalVariable] | None = None,
        *,
        use_cache: bool = True,
    ) -> list[TimeSeries]:
        """Return a `TimeSeries` per canonical variable requested."""

        variables = variables or DEFAULT_PARAMETERS
        settings = get_settings()
        params = {
            "parameters": ",".join(_canonical_to_power(v) for v in variables),
            "community": self.community.upper(),
            "longitude": location.lon,
            "latitude": location.lat,
            "start": start.strftime("%Y%m%d"),
            "end": end.strftime("%Y%m%d"),
            "format": "JSON",
        }

        cache_key = make_key("power:daily_point", params)

        async def fetch() -> dict[str, Any]:
            async with async_client(base_url=self.base_url, timeout=self.timeout) as c:
                return await self._get(c, "/temporal/daily/point", params=params)

        if use_cache:
            data, _ = await async_cached_or_set(cache_key, fetch, settings.cache_ttl_history)
        else:
            data = await fetch()

        return self._parse_point_response(data, location, variables)

    async def climatology_point(
        self,
        location: Location,
        variables: list[CanonicalVariable] | None = None,
    ) -> list[TimeSeries]:
        """Long-term monthly climatology for the given point."""

        variables = variables or DEFAULT_PARAMETERS
        settings = get_settings()
        params = {
            "parameters": ",".join(_canonical_to_power(v) for v in variables),
            "community": self.community.upper(),
            "longitude": location.lon,
            "latitude": location.lat,
            "format": "JSON",
        }

        cache_key = make_key("power:climatology_point", params)

        async def fetch() -> dict[str, Any]:
            async with async_client(base_url=self.base_url, timeout=self.timeout) as c:
                return await self._get(c, "/temporal/climatology/point", params=params)

        data, _ = await async_cached_or_set(cache_key, fetch, settings.cache_ttl_history)
        return self._parse_point_response(data, location, variables, resolution="climatology")

    @staticmethod
    async def _get(c: httpx.AsyncClient, path: str, *, params: dict) -> dict[str, Any]:
        r = await request_with_retry(c, "GET", path, params=params)
        if r.status_code >= 400:
            raise UpstreamError(
                f"NASA POWER returned HTTP {r.status_code}: {r.text[:200]}",
                details={"status": r.status_code},
            )
        return r.json()

    def _parse_point_response(
        self,
        payload: dict[str, Any],
        location: Location,
        variables: list[CanonicalVariable],
        *,
        resolution: str = "daily",
    ) -> list[TimeSeries]:
        parameters = payload.get("properties", {}).get("parameter", {})
        header = payload.get("header", {})
        units = payload.get("parameters", {})

        series: list[TimeSeries] = []
        requested = {_canonical_to_power(v): v for v in variables}
        for power_name, by_date in parameters.items():
            canonical = requested.get(power_name) or _power_to_canonical(power_name)
            if canonical is None:
                continue
            points: list[TimePoint] = []
            for key, value in by_date.items():
                parsed = _parse_power_date(key)
                if parsed is None:
                    continue
                v = None if value is None or value == POWER_MISSING else float(value)
                points.append(TimePoint(date=parsed, value=v))

            points.sort(key=lambda p: p.date)
            series.append(
                TimeSeries(
                    source=self.source_name,
                    variable=canonical,
                    unit=CANONICAL_VARIABLES[canonical].unit,
                    location=location,
                    temporal_resolution=resolution,  # type: ignore[arg-type]
                    points=points,
                    metadata={
                        "source_variable": power_name,
                        "source_unit": units.get(power_name, {}).get("units"),
                        "community": self.community,
                        "api": "nasa_power",
                        "header_title": header.get("title"),
                    },
                )
            )
        series.sort(key=lambda s: s.variable.value)
        return series


def _parse_power_date(key: str) -> date | None:
    """POWER returns daily keys as YYYYMMDD and climatology as YYYYMM / month names.

    For climatology this helper only handles the numeric YYYYMM form (months 1..12 as
    first-of-month dates). Non-numeric keys are returned as `None`.
    """
    try:
        if len(key) == 8:
            return datetime.strptime(key, "%Y%m%d").date()
        if len(key) == 6:
            return datetime.strptime(key + "01", "%Y%m%d").date()
    except ValueError:
        pass
    return None
