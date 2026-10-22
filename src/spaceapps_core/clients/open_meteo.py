from __future__ import annotations

from datetime import date, datetime
from typing import Any

import httpx

from ..core.cache import async_cached_or_set, make_key
from ..core.config import get_settings
from ..core.errors import InvalidRequestError, UpstreamError
from ..core.http import async_client, request_with_retry
from ..schemas.common import Location, TimePoint, TimeSeries
from ..schemas.variables import CANONICAL_VARIABLES, CanonicalVariable
from .base import BaseClient

OPEN_METEO_BASE_URL = "https://api.open-meteo.com/v1"
MAX_FORECAST_DAYS = 16

DEFAULT_FORECAST_VARIABLES: list[CanonicalVariable] = [
    CanonicalVariable.T2M_MEAN,
    CanonicalVariable.T2M_MAX,
    CanonicalVariable.T2M_MIN,
    CanonicalVariable.PRECIPITATION,
    CanonicalVariable.SOLAR_RADIATION,
    CanonicalVariable.WIND2M,
]


def _canonical_to_om(variable: CanonicalVariable) -> str:
    alias = CANONICAL_VARIABLES[variable].source_aliases.get("open_meteo")
    if alias is None:
        raise ValueError(f"Open-Meteo has no daily alias for {variable}.")
    return alias


class OpenMeteoClient(BaseClient):
    """Open-Meteo forecast client (no authentication).

    Documentation: https://open-meteo.com/en/docs
    """

    source_name = "open_meteo"

    def __init__(
        self,
        *,
        timeout: float | None = None,
        base_url: str = OPEN_METEO_BASE_URL,
    ) -> None:
        self.timeout = timeout
        self.base_url = base_url

    async def forecast(
        self,
        location: Location,
        *,
        start: date | None = None,
        end: date | None = None,
        forecast_days: int | None = None,
        variables: list[CanonicalVariable] | None = None,
        use_cache: bool = True,
    ) -> list[TimeSeries]:
        """Daily forecast.

        Either provide `start`/`end` (both or neither) or `forecast_days` (1-16).
        If none are provided the client defaults to 7 forecast days.
        """

        variables = variables or DEFAULT_FORECAST_VARIABLES
        om_variables = [_canonical_to_om(v) for v in variables]

        params: dict[str, Any] = {
            "latitude": location.lat,
            "longitude": location.lon,
            "daily": ",".join(om_variables),
            "timezone": "UTC",
            "wind_speed_unit": "ms",
        }

        if start is not None and end is not None:
            if end < start:
                raise InvalidRequestError("`end` must be >= `start`.")
            params["start_date"] = start.isoformat()
            params["end_date"] = end.isoformat()
        elif start is not None or end is not None:
            raise InvalidRequestError(
                "Provide both `start` and `end` or neither (use `forecast_days`)."
            )
        else:
            days = forecast_days if forecast_days is not None else 7
            if not 1 <= days <= MAX_FORECAST_DAYS:
                raise InvalidRequestError(
                    f"`forecast_days` must be between 1 and {MAX_FORECAST_DAYS}."
                )
            params["forecast_days"] = days

        settings = get_settings()
        cache_key = make_key("open_meteo:forecast", params)

        async def fetch() -> dict[str, Any]:
            async with async_client(base_url=self.base_url, timeout=self.timeout) as c:
                return await self._get(c, "/forecast", params=params)

        if use_cache:
            data, _ = await async_cached_or_set(cache_key, fetch, settings.cache_ttl_forecast)
        else:
            data = await fetch()

        return self._parse_forecast(data, location, variables)

    @staticmethod
    async def _get(c: httpx.AsyncClient, path: str, *, params: dict) -> dict[str, Any]:
        r = await request_with_retry(c, "GET", path, params=params)
        if r.status_code >= 400:
            raise UpstreamError(
                f"Open-Meteo returned HTTP {r.status_code}: {r.text[:200]}",
                details={"status": r.status_code},
            )
        return r.json()

    def _parse_forecast(
        self,
        payload: dict[str, Any],
        location: Location,
        variables: list[CanonicalVariable],
    ) -> list[TimeSeries]:
        daily = payload.get("daily") or {}
        daily_units = payload.get("daily_units") or {}
        times = daily.get("time") or []
        dates = [datetime.strptime(t, "%Y-%m-%d").date() for t in times]

        series: list[TimeSeries] = []
        for canonical in variables:
            om_name = _canonical_to_om(canonical)
            values = daily.get(om_name) or []
            points = [
                TimePoint(date=d, value=(float(v) if v is not None else None))
                for d, v in zip(dates, values, strict=False)
            ]
            series.append(
                TimeSeries(
                    source=self.source_name,
                    variable=canonical,
                    unit=CANONICAL_VARIABLES[canonical].unit,
                    location=location,
                    temporal_resolution="daily",
                    points=points,
                    metadata={
                        "source_variable": om_name,
                        "source_unit": daily_units.get(om_name),
                        "api": "open_meteo",
                        "timezone": payload.get("timezone"),
                        "model_elevation": payload.get("elevation"),
                    },
                )
            )
        return series
