from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .common import Location, TimeSeries


class JobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location: Location
    start: date
    end: date
    product: str = Field(..., description="Upstream product identifier (e.g. MOD13Q1.061).")
    layers: list[str] = Field(default_factory=list, description="Upstream layer names.")
    label: str | None = None


class JobStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    source: str
    status: Literal["pending", "queued", "running", "done", "failed"]
    progress: float | None = Field(default=None, ge=0, le=1)
    created_at: datetime
    updated_at: datetime
    message: str | None = None


class JobResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    status: JobStatus
    series: list[TimeSeries] = Field(default_factory=list)
    raw: dict[str, Any] | None = None
