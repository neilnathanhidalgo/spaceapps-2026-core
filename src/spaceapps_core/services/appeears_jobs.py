"""Thin registry mapping AppEEARS task_ids to the canonical layers we requested.

Persisted in diskcache so the API can parse point-task CSV results into
TimeSeries without the caller needing to re-specify the product/layer mapping.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from ..clients.appeears import AppEEARSLayer
from ..core.cache import get_cache
from ..schemas.common import Location
from ..schemas.variables import CanonicalVariable

_PREFIX = "appeears:job:"
_TTL = 30 * 24 * 60 * 60


@dataclass
class JobRegistryEntry:
    task_id: str
    source: str
    location: Location
    layers: list[AppEEARSLayer]

    def to_cache(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "source": self.source,
            "location": self.location.model_dump(),
            "layers": [asdict(layer) for layer in self.layers],
        }

    @classmethod
    def from_cache(cls, data: dict[str, Any]) -> JobRegistryEntry:
        return cls(
            task_id=data["task_id"],
            source=data["source"],
            location=Location(**data["location"]),
            layers=[
                AppEEARSLayer(
                    product=layer["product"],
                    layer=layer["layer"],
                    canonical=CanonicalVariable(layer["canonical"]),
                )
                for layer in data["layers"]
            ],
        )


def _key(task_id: str) -> str:
    return _PREFIX + task_id


def register_job(entry: JobRegistryEntry) -> None:
    get_cache().set(_key(entry.task_id), entry.to_cache(), expire=_TTL)


def get_job(task_id: str) -> JobRegistryEntry | None:
    raw = get_cache().get(_key(task_id))
    if raw is None:
        return None
    return JobRegistryEntry.from_cache(dict(raw))
