"""Merge multiple sources into a single daily feature table.

Produces a wide `pandas.DataFrame` indexed by date with one column per
canonical variable, suffixed by source when the same variable comes from
more than one source (e.g. precipitation / precipitation_imerg).
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from ..clients.earthdata import EarthdataClient
from ..clients.open_meteo import OpenMeteoClient
from ..clients.power import DEFAULT_PARAMETERS, PowerClient
from ..core.config import get_settings
from ..schemas.common import Location, TimeSeries
from ..schemas.variables import CanonicalVariable


def _series_to_frame(series: list[TimeSeries], suffix: str | None = None) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for s in series:
        col = s.variable.value if suffix is None else f"{s.variable.value}_{suffix}"
        frames.append(
            pd.DataFrame(
                {
                    "date": [p.date for p in s.points],
                    col: [p.value for p in s.points],
                }
            ).set_index("date")
        )
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, axis=1)


async def build_features(
    *,
    location: Location,
    start: date,
    end: date,
    variables: list[CanonicalVariable] | None = None,
    include_forecast: bool = False,
    include_imerg: bool = False,
) -> pd.DataFrame:
    variables = variables or DEFAULT_PARAMETERS
    settings = get_settings()

    power = await PowerClient().daily_point(
        location=location,
        start=start,
        end=end,
        variables=variables,
    )
    base = _series_to_frame(power)

    if include_forecast:
        om = await OpenMeteoClient().forecast(
            location=location,
            start=start,
            end=end,
            variables=[v for v in variables if v != CanonicalVariable.RH2M],
        )
        base = base.combine_first(_series_to_frame(om, suffix="forecast"))

    if include_imerg and settings.earthdata_configured:
        imerg = await EarthdataClient().imerg_daily_point(location=location, start=start, end=end)
        base = base.combine_first(_series_to_frame([imerg], suffix="imerg"))

    base.index.name = "date"
    base = base.sort_index()
    return base.reset_index()
