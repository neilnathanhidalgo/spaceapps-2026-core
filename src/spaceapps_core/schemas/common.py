from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .variables import CanonicalVariable


class Location(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lat: float = Field(..., ge=-90, le=90, description="Latitude in decimal degrees.")
    lon: float = Field(..., ge=-180, le=180, description="Longitude in decimal degrees.")
    geometry: dict[str, Any] | None = Field(
        default=None,
        description="Optional GeoJSON geometry (Polygon/MultiPolygon) for an area of interest.",
    )


class TimePoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: date
    value: float | None = Field(
        default=None,
        description="Value in the series unit. Null means missing/NaN.",
    )


class TimeSeries(BaseModel):
    """Normalized time series returned by every data client."""

    model_config = ConfigDict(extra="forbid")

    source: str = Field(..., description="Short identifier of the upstream source, e.g. 'power'.")
    variable: CanonicalVariable
    unit: str
    location: Location
    temporal_resolution: Literal["daily", "hourly", "monthly", "climatology"] = "daily"
    points: list[TimePoint] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    retrieved_at: datetime = Field(default_factory=datetime.utcnow)


class SourceHealth(BaseModel):
    name: str
    status: Literal["ok", "error", "not_configured", "skipped"]
    latency_ms: float | None = None
    message: str | None = None


class SourcesHealth(BaseModel):
    sources: list[SourceHealth]


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    class ErrorBody(BaseModel):
        code: str
        message: str
        details: dict[str, Any] | None = None

    error: ErrorBody
