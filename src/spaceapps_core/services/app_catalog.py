"""Catalog the app shows to the farmer, straight from the parameter file."""

from __future__ import annotations

from ..schemas.recommendation import (
    AppCatalog,
    CatalogCrop,
    CatalogPriority,
    CatalogRestriction,
    CatalogSoilTexture,
    CropWaterNeed,
)
from .agro_config import AgroConfig, CropConfig, ThresholdsConfig, load_agro_config


def crop_water_need(crop: CropConfig, thresholds: ThresholdsConfig) -> CropWaterNeed:
    """Band of the crop's water index, to say "pide poca agua" without m³."""
    if crop.water_index >= thresholds.crop_water_need_high_index:
        return "high"
    if crop.water_index >= thresholds.crop_water_need_medium_index:
        return "medium"
    return "low"


def catalog_crop(crop: CropConfig, thresholds: ThresholdsConfig) -> CatalogCrop:
    """The crop's factsheet as the app reads it: water, duration and nitrogen."""
    return CatalogCrop(
        id=crop.id,
        name=crop.name,
        cycle_months=crop.cycle_months,
        soil_impact=crop.soil_impact,
        water_need=crop_water_need(crop, thresholds),
        water_index=crop.water_index,
        fixes_nitrogen=crop.fixes_nitrogen,
    )


def build_catalog(config: AgroConfig | None = None) -> AppCatalog:
    """Crops, priorities, restrictions and soil answers, in the order of the file."""
    config = config or load_agro_config()
    return AppCatalog(
        crops=[catalog_crop(crop, config.thresholds) for crop in config.crops],
        priorities=[
            CatalogPriority(id=priority.id, name=priority.name, phrase=priority.phrase)
            for priority in config.priorities
        ],
        restrictions=[
            CatalogRestriction(id=restriction.id, name=restriction.name)
            for restriction in config.restrictions
        ],
        soil_textures=[
            CatalogSoilTexture(
                id=texture.id,
                name=texture.name,
                description=texture.description,
            )
            for texture in config.soil_textures
        ],
        soil_texture_question=config.content.soil_texture_question,
        max_rotation_crops=config.thresholds.max_custom_rotation_crops,
        example_parameters=config.example_parameters,
    )
