"""NEX-GDDP-CMIP6 downscaled climate projections on anonymous S3.

Bucket: s3://nex-gddp-cmip6
Path layout:
  NEX-GDDP-CMIP6/<model>/<scenario>/<ensemble>/<variable>/<variable>_day_<model>_<scenario>_<ensemble>_<grid>_<year>.nc

Variables used here (CMIP6 standard):
  - pr      (kg m-2 s-1) -> mm/day         [* 86400]
  - tas     (K)          -> degC            [- 273.15]
  - tasmax  (K)          -> degC            [- 273.15]
  - tasmin  (K)          -> degC            [- 273.15]
"""

from __future__ import annotations

from datetime import date
from typing import Any

from ..core.cache import async_cached_or_set, make_key
from ..core.config import get_settings
from ..core.errors import InvalidRequestError, UpstreamError
from ..schemas.common import Location, TimePoint, TimeSeries
from ..schemas.variables import CANONICAL_VARIABLES, CanonicalVariable
from .base import BaseClient

BUCKET_PREFIX = "s3://nex-gddp-cmip6/NEX-GDDP-CMIP6"
DEFAULT_MODEL = "ACCESS-CM2"
DEFAULT_ENSEMBLE = "r1i1p1f1"
DEFAULT_GRID = "gn"
SUPPORTED_SCENARIOS = {"historical", "ssp126", "ssp245", "ssp370", "ssp585"}

DEFAULT_VARIABLES: list[CanonicalVariable] = [
    CanonicalVariable.T2M_MEAN,
    CanonicalVariable.T2M_MAX,
    CanonicalVariable.T2M_MIN,
    CanonicalVariable.PRECIPITATION,
]


def _canonical_to_cmip(variable: CanonicalVariable) -> str:
    alias = CANONICAL_VARIABLES[variable].source_aliases.get("nex_gddp")
    if alias is None:
        raise InvalidRequestError(
            f"NEX-GDDP-CMIP6 has no mapping for canonical variable {variable}."
        )
    return alias


class NexGddpClient(BaseClient):
    source_name = "nex_gddp"

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        ensemble: str = DEFAULT_ENSEMBLE,
        grid: str = DEFAULT_GRID,
    ) -> None:
        self.model = model
        self.ensemble = ensemble
        self.grid = grid

    async def projections_point(
        self,
        *,
        location: Location,
        start: date,
        end: date,
        scenario: str = "ssp245",
        variables: list[CanonicalVariable] | None = None,
    ) -> list[TimeSeries]:
        if scenario not in SUPPORTED_SCENARIOS:
            raise InvalidRequestError(
                f"Unsupported scenario '{scenario}'. Pick one of: {sorted(SUPPORTED_SCENARIOS)}."
            )
        if end < start:
            raise InvalidRequestError("`end` must be >= `start`.")

        variables = variables or DEFAULT_VARIABLES
        settings = get_settings()

        results: list[TimeSeries] = []
        for canonical in variables:
            cmip = _canonical_to_cmip(canonical)
            cache_key = make_key(
                "nex_gddp:point",
                {
                    "lat": location.lat,
                    "lon": location.lon,
                    "start": start,
                    "end": end,
                    "scenario": scenario,
                    "model": self.model,
                    "ensemble": self.ensemble,
                    "variable": cmip,
                },
            )

            async def fetch(
                _cmip: str = cmip,
                _canonical: CanonicalVariable = canonical,
            ) -> dict[str, Any]:
                points = await _run_blocking(
                    self._fetch_variable_sync,
                    variable_cmip=_cmip,
                    scenario=scenario,
                    start=start,
                    end=end,
                    location=location,
                )
                return {"points": points, "variable": _cmip}

            data, _ = await async_cached_or_set(cache_key, fetch, settings.cache_ttl_projections)

            points = [
                TimePoint(date=date.fromisoformat(p["date"]), value=p["value"])
                for p in data["points"]
            ]
            results.append(
                TimeSeries(
                    source=self.source_name,
                    variable=canonical,
                    unit=CANONICAL_VARIABLES[canonical].unit,
                    location=location,
                    temporal_resolution="daily",
                    points=points,
                    metadata={
                        "model": self.model,
                        "scenario": scenario,
                        "ensemble": self.ensemble,
                        "grid": self.grid,
                        "source_variable": data["variable"],
                        "api": "nex_gddp_cmip6",
                    },
                )
            )
        return results

    def _fetch_variable_sync(
        self,
        *,
        variable_cmip: str,
        scenario: str,
        start: date,
        end: date,
        location: Location,
    ) -> list[dict[str, Any]]:
        import s3fs
        import xarray as xr

        fs = s3fs.S3FileSystem(anon=True)
        collected: list[dict[str, Any]] = []
        lon = location.lon % 360  # NEX-GDDP longitudes are 0..360

        for year in range(start.year, end.year + 1):
            path = (
                f"{BUCKET_PREFIX}/{self.model}/{scenario}/{self.ensemble}/"
                f"{variable_cmip}/{variable_cmip}_day_{self.model}_{scenario}_"
                f"{self.ensemble}_{self.grid}_{year}.nc"
            )
            try:
                with fs.open(path, "rb") as fh, xr.open_dataset(fh) as ds:
                    nearest = ds[variable_cmip].sel(lat=location.lat, lon=lon, method="nearest")
                    times = ds.indexes.get("time")
                    if times is None:
                        continue
                    for ts, val in zip(times, nearest.values.ravel(), strict=False):
                        d = _to_date(ts)
                        if d is None or d < start or d > end:
                            continue
                        v = _convert(variable_cmip, float(val))
                        collected.append({"date": d.isoformat(), "value": v})
            except FileNotFoundError:
                continue
            except Exception as e:
                raise UpstreamError(f"NEX-GDDP read failed for {path}: {e}") from e

        collected.sort(key=lambda p: p["date"])
        return collected


def _to_date(value: Any) -> date | None:
    try:
        return value.date()
    except AttributeError:
        pass
    try:
        import numpy as np

        s = np.datetime_as_string(np.datetime64(value), unit="D")
        return date.fromisoformat(s)
    except Exception:
        return None


def _convert(variable_cmip: str, value: float) -> float | None:
    if value != value:  # NaN
        return None
    if variable_cmip == "pr":
        return value * 86400.0
    if variable_cmip in {"tas", "tasmax", "tasmin"}:
        return value - 273.15
    return value


async def _run_blocking(fn, **kwargs):
    import asyncio

    return await asyncio.to_thread(lambda: fn(**kwargs))
