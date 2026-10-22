from __future__ import annotations

from typing import TYPE_CHECKING

from ..schemas.common import TimeSeries

if TYPE_CHECKING:
    import pandas as pd


class BaseClient:
    """Common surface for every data client.

    Subclasses implement source-specific fetch methods but should always return
    a `TimeSeries` (or a list of them) so downstream consumers (API routers,
    notebooks, feature builders) can treat all sources uniformly.
    """

    source_name: str = "base"

    @staticmethod
    def to_dataframe(series: TimeSeries | list[TimeSeries]) -> pd.DataFrame:
        import pandas as pd

        if isinstance(series, TimeSeries):
            series = [series]

        rows: list[dict] = []
        for s in series:
            for p in s.points:
                rows.append(
                    {
                        "date": p.date,
                        "value": p.value,
                        "variable": s.variable.value,
                        "unit": s.unit,
                        "source": s.source,
                        "lat": s.location.lat,
                        "lon": s.location.lon,
                    }
                )
        return pd.DataFrame(rows)
