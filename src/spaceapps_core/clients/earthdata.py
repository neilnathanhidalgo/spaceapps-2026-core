"""Earthdata client built on top of `earthaccess`.

Specialized for GPM IMERG daily precipitation (short_name GPM_3IMERGDF) but
exposes a generic `search_granules` method so other datasets can be added.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

from ..core.cache import async_cached_or_set, make_key
from ..core.config import get_settings
from ..core.errors import NotConfiguredError, UpstreamError
from ..schemas.common import Location, TimePoint, TimeSeries
from ..schemas.variables import CANONICAL_VARIABLES, CanonicalVariable
from .base import BaseClient

if TYPE_CHECKING:
    import earthaccess


IMERG_DAILY_SHORT_NAME = "GPM_3IMERGDF"
IMERG_PRECIP_VARIABLE = "precipitation"


class EarthdataClient(BaseClient):
    """Thin wrapper around `earthaccess` with on-demand login.

    Keeping the import lazy means the rest of the application can start even
    when the user has not provided Earthdata credentials.
    """

    source_name = "earthdata"
    _logged_in: bool = False

    def __init__(self) -> None:
        self._settings = get_settings()

    def _ensure_credentials(self) -> None:
        if not self._settings.earthdata_configured:
            raise NotConfiguredError(
                "Earthdata requires EARTHDATA_USERNAME and EARTHDATA_PASSWORD."
            )

    def _login(self) -> None:
        if self._logged_in:
            return
        self._ensure_credentials()
        import os

        import earthaccess

        os.environ["EARTHDATA_USERNAME"] = self._settings.earthdata_username
        os.environ["EARTHDATA_PASSWORD"] = self._settings.earthdata_password

        auth = earthaccess.login(strategy="environment", persist=False)
        if not getattr(auth, "authenticated", False):
            raise UpstreamError("Earthdata login failed; check EARTHDATA credentials.")
        type(self)._logged_in = True

    def search_granules(
        self,
        *,
        short_name: str,
        location: Location,
        start: date,
        end: date,
        version: str | None = None,
    ) -> list[earthaccess.search.DataGranule]:
        self._login()
        import earthaccess

        kwargs: dict[str, Any] = {
            "short_name": short_name,
            "point": (location.lon, location.lat),
            "temporal": (start.isoformat(), end.isoformat()),
        }
        if version is not None:
            kwargs["version"] = version
        return earthaccess.search_data(**kwargs)

    async def imerg_daily_point(
        self,
        *,
        location: Location,
        start: date,
        end: date,
    ) -> TimeSeries:
        settings = get_settings()
        key = make_key(
            "earthdata:imerg_daily",
            {"lat": location.lat, "lon": location.lon, "start": start, "end": end},
        )

        async def fetch() -> dict[str, Any]:
            points = await _run_blocking(
                self._imerg_daily_sync, location=location, start=start, end=end
            )
            return {"points": points}

        data, _ = await async_cached_or_set(key, fetch, settings.cache_ttl_history)
        points = [
            TimePoint(date=date.fromisoformat(p["date"]), value=p["value"]) for p in data["points"]
        ]

        return TimeSeries(
            source=self.source_name,
            variable=CanonicalVariable.PRECIPITATION,
            unit=CANONICAL_VARIABLES[CanonicalVariable.PRECIPITATION].unit,
            location=location,
            temporal_resolution="daily",
            points=points,
            metadata={
                "short_name": IMERG_DAILY_SHORT_NAME,
                "variable": IMERG_PRECIP_VARIABLE,
                "api": "earthaccess",
            },
        )

    def _imerg_daily_sync(
        self,
        *,
        location: Location,
        start: date,
        end: date,
    ) -> list[dict[str, Any]]:
        import earthaccess
        import xarray as xr

        granules = self.search_granules(
            short_name=IMERG_DAILY_SHORT_NAME,
            location=location,
            start=start,
            end=end,
        )
        if not granules:
            return []

        files = earthaccess.open(granules)
        points: list[dict[str, Any]] = []
        for fh in files:
            try:
                with xr.open_dataset(fh) as ds:
                    da = ds[IMERG_PRECIP_VARIABLE]
                    nearest = da.sel(lat=location.lat, lon=location.lon, method="nearest")
                    time_coord = ds.indexes.get("time")
                    if time_coord is None:
                        continue
                    for ts, val in zip(time_coord, nearest.values.ravel(), strict=False):
                        iso = _coord_to_date_iso(ts)
                        v = None if val is None else float(val)
                        points.append({"date": iso, "value": v})
            except Exception:
                continue

        points.sort(key=lambda p: p["date"])
        return points


def _coord_to_date_iso(value: Any) -> str:
    try:
        return value.date().isoformat()
    except AttributeError:
        import numpy as np

        return str(np.datetime_as_string(np.datetime64(value), unit="D"))


async def _run_blocking(fn, **kwargs):
    import asyncio

    return await asyncio.to_thread(lambda: fn(**kwargs))
