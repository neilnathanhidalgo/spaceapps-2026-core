"""Agronomic parameters of the recommendation engine, loaded from JSON.

Every number and text the engine needs lives in `data/agro_config.json`
(override the path with `AGRO_CONFIG_PATH`). The data team edits that file;
this module only loads it and validates that it is coherent.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ..core.config import get_settings
from ..core.errors import NotConfiguredError
from ..schemas.recommendation import (
    SCENARIO_IDS,
    RankingCriterion,
    ScenarioId,
    SoilImpactKind,
)

PACKAGED_CONFIG_PATH = Path(__file__).resolve().parent.parent / "data" / "agro_config.json"

SOIL_IMPACT_SCORES: dict[SoilImpactKind, int] = {
    "degrades": -1,
    "neutral": 0,
    "improves": 1,
    "improves_a_lot": 2,
}


class _Block(BaseModel):
    """Config block that can be flagged as carrying example values."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    is_example: bool = Field(default=False, alias="_example")


class CropConfig(_Block):
    id: str
    name: str
    kc_by_month: list[float] = Field(
        ...,
        min_length=1,
        description="One crop coefficient per month of the cycle; its length is the duration.",
    )
    soil_impact: SoilImpactKind
    rationale: str
    evidence: str
    benefits: str
    unknowns: str
    risks: str
    planting_instructions: str

    @property
    def cycle_months(self) -> int:
        return len(self.kc_by_month)

    @property
    def soil_score(self) -> int:
        return SOIL_IMPACT_SCORES[self.soil_impact]


class RotationConfig(_Block):
    id: str
    crop_ids: list[str] = Field(..., min_length=1, description="Crops in planting order.")


class ScenariosConfig(_Block):
    """Reference years whose observed climate stands for each scenario."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    heavy_rains: list[int] = Field(..., min_length=1)
    normal: list[int] = Field(..., min_length=1)
    dry: list[int] = Field(..., min_length=1)

    @model_validator(mode="after")
    def _check_years(self) -> Self:
        for scenario in SCENARIO_IDS:
            for year in self.years_for(scenario):
                if year < 1981:
                    raise ValueError(f"NASA POWER starts in 1981; got {year} in {scenario}.")
        return self

    def years_for(self, scenario: ScenarioId) -> list[int]:
        return getattr(self, scenario)  # type: ignore[no-any-return]


class ThresholdsConfig(_Block):
    risk_month_rain_mm: float = Field(
        ..., gt=0, description="Monthly rainfall from which a month counts as risky."
    )
    effective_rain_fraction: float = Field(
        ..., gt=0, le=1, description="Share of rainfall the crop can actually use."
    )
    low_water_m3_per_ha: float = Field(
        ...,
        gt=0,
        description='Water per hectare from which "Tendré poca agua" rules an option out.',
    )
    climate_risk_medium_months: int = Field(..., ge=1)
    climate_risk_high_months: int = Field(..., ge=1)
    soil_baseline_score: int = Field(..., ge=0, le=3, description="0 very tired … 3 good.")
    soil_campaigns_before_penalty: int = Field(
        ..., ge=0, description="Campaigns with the same crop that do not move the soil score yet."
    )
    soil_horizon_months: int = Field(..., ge=1, description='Horizon of "soil in two years".')
    decision_lead_days: int = Field(
        ..., ge=0, description="Days before the planting date the farmer has to decide."
    )

    @model_validator(mode="after")
    def _check_risk_levels(self) -> Self:
        if self.climate_risk_high_months < self.climate_risk_medium_months:
            raise ValueError("`climate_risk_high_months` must be >= `climate_risk_medium_months`.")
        return self


class PriorityConfig(_Block):
    id: str
    name: str
    phrase: str
    criterion: RankingCriterion


class RestrictionConfig(_Block):
    id: str
    name: str
    excludes_crop_ids: list[str] = Field(default_factory=list)
    excludes_high_water_use: bool = Field(
        default=False,
        description="Rules out options above `thresholds.low_water_m3_per_ha` in any scenario.",
    )


class DefaultsConfig(_Block):
    last_crop_id: str
    current_practice_campaigns: int = Field(
        ..., ge=1, description="How many times the last crop is repeated as the baseline."
    )


class ContentConfig(_Block):
    irrigation_source: str
    scenario_notes: dict[ScenarioId, str]
    repeat_warnings: dict[ScenarioId, str]
    soil_findings: list[str] = Field(
        ..., description="Templates; `{campaigns}` and `{crop}` are filled in."
    )

    @model_validator(mode="after")
    def _check_every_scenario(self) -> Self:
        for field, texts in (
            ("scenario_notes", self.scenario_notes),
            ("repeat_warnings", self.repeat_warnings),
        ):
            missing = set(SCENARIO_IDS) - set(texts)
            if missing:
                raise ValueError(f"`{field}` is missing {sorted(missing)}.")
        return self


class AgroConfig(BaseModel):
    """Whole parameter file, already validated and cross-checked."""

    model_config = ConfigDict(extra="forbid")

    crops: list[CropConfig] = Field(..., min_length=1)
    rotations: list[RotationConfig] = Field(..., min_length=1)
    scenarios: ScenariosConfig
    thresholds: ThresholdsConfig
    priorities: list[PriorityConfig] = Field(..., min_length=1)
    restrictions: list[RestrictionConfig] = Field(default_factory=list)
    defaults: DefaultsConfig
    content: ContentConfig

    @model_validator(mode="after")
    def _check_references(self) -> Self:
        _reject_duplicates("crops", [c.id for c in self.crops])
        _reject_duplicates("rotations", [r.id for r in self.rotations])
        _reject_duplicates("priorities", [p.id for p in self.priorities])
        _reject_duplicates("restrictions", [r.id for r in self.restrictions])

        known = {crop.id for crop in self.crops}
        for rotation in self.rotations:
            _reject_unknown(f"rotations.{rotation.id}", rotation.crop_ids, known)
        for restriction in self.restrictions:
            _reject_unknown(f"restrictions.{restriction.id}", restriction.excludes_crop_ids, known)
        _reject_unknown("defaults.last_crop_id", [self.defaults.last_crop_id], known)
        return self

    @property
    def example_parameters(self) -> bool:
        """True while any block still carries example values."""
        blocks: list[_Block] = [
            *self.crops,
            *self.rotations,
            *self.priorities,
            *self.restrictions,
            self.scenarios,
            self.thresholds,
            self.defaults,
            self.content,
        ]
        return any(block.is_example for block in blocks)

    def crop(self, crop_id: str) -> CropConfig:
        """Crop with [crop_id]. Raises `KeyError` when it does not exist."""
        for crop in self.crops:
            if crop.id == crop_id:
                return crop
        raise KeyError(crop_id)

    def priority(self, priority_id: str | None) -> PriorityConfig:
        """Priority with [priority_id], or the suggested one when it is null."""
        if priority_id is None:
            return self.priorities[0]
        for priority in self.priorities:
            if priority.id == priority_id:
                return priority
        raise KeyError(priority_id)

    def restriction(self, restriction_id: str) -> RestrictionConfig:
        """Restriction with [restriction_id]. Raises `KeyError` when unknown."""
        for restriction in self.restrictions:
            if restriction.id == restriction_id:
                return restriction
        raise KeyError(restriction_id)


def _reject_duplicates(block: str, ids: list[str]) -> None:
    duplicated = sorted({name for name in ids if ids.count(name) > 1})
    if duplicated:
        raise ValueError(f"`{block}` has duplicated ids: {duplicated}.")


def _reject_unknown(block: str, crop_ids: list[str], known: set[str]) -> None:
    unknown = sorted(set(crop_ids) - known)
    if unknown:
        raise ValueError(f"`{block}` points to crops that do not exist: {unknown}.")


def parse_agro_config(raw: object) -> AgroConfig:
    """Validate already-decoded JSON. Importable from a notebook."""
    return AgroConfig.model_validate(raw)


@lru_cache
def load_agro_config(path: str | None = None) -> AgroConfig:
    """Read and validate the parameter file.

    `path` defaults to `AGRO_CONFIG_PATH` and, when that is empty, to the
    copy packaged with the library.
    """
    resolved = Path(path or get_settings().agro_config_path or PACKAGED_CONFIG_PATH)
    try:
        return parse_agro_config(json.loads(resolved.read_text(encoding="utf-8")))
    except OSError as error:
        raise NotConfiguredError(
            f"Agronomic parameters not readable at {resolved}.",
            details={"path": str(resolved)},
        ) from error
    except (json.JSONDecodeError, ValidationError, ValueError) as error:
        raise NotConfiguredError(
            f"Agronomic parameters at {resolved} are invalid: {error}",
            details={"path": str(resolved)},
        ) from error
