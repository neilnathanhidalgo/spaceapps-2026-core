"""Catalog the app shows to the farmer, straight from the parameter file."""

from __future__ import annotations

from ..schemas.recommendation import (
    AppCatalog,
    CatalogCrop,
    CatalogPriority,
    CatalogRestriction,
)
from .agro_config import AgroConfig, load_agro_config


def build_catalog(config: AgroConfig | None = None) -> AppCatalog:
    """Crops, priorities and restrictions, in the order of the file."""
    config = config or load_agro_config()
    return AppCatalog(
        crops=[
            CatalogCrop(
                id=crop.id,
                name=crop.name,
                cycle_months=crop.cycle_months,
                soil_impact=crop.soil_impact,
            )
            for crop in config.crops
        ],
        priorities=[
            CatalogPriority(id=priority.id, name=priority.name, phrase=priority.phrase)
            for priority in config.priorities
        ],
        restrictions=[
            CatalogRestriction(id=restriction.id, name=restriction.name)
            for restriction in config.restrictions
        ],
        example_parameters=config.example_parameters,
    )
