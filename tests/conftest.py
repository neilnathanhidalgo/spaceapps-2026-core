from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator

import pytest

os.environ.setdefault("CACHE_DIR", tempfile.mkdtemp(prefix="spaceapps-cache-"))
os.environ.setdefault("CORS_ORIGINS", "*")


@pytest.fixture(autouse=True)
def _clear_disk_cache() -> Iterator[None]:
    """Keep tests independent: wipe the on-disk cache around every test."""
    from spaceapps_core.core.cache import get_cache

    get_cache().clear()
    yield
    get_cache().clear()


def agro_thresholds(**overrides: object):
    """Thresholds of the recommendation engine, with example values."""
    from spaceapps_core.services.agro_config import ThresholdsConfig

    values: dict[str, object] = {
        "risk_month_rain_mm": 150.0,
        "effective_rain_fraction": 0.8,
        "low_water_m3_per_ha": 9000.0,
        "climate_risk_medium_months": 1,
        "climate_risk_high_months": 2,
        "soil_baseline_score": 3,
        "soil_campaigns_before_penalty": 1,
        "soil_horizon_months": 24,
        "decision_lead_days": 0,
        "sandy_sand_percent": 70.0,
        "clayey_clay_percent": 35.0,
        "effective_rain_fraction_by_texture": {"sandy": 0.6, "clayey": 0.9},
        "soil_organic_carbon_low_g_kg": 10.0,
        "soil_organic_carbon_high_g_kg": 20.0,
        "soil_vegetation_decline_penalty": 1,
        "vegetation_trend_years": 5,
        "vegetation_flat_tolerance": 0.05,
        "vegetation_season_start_month": 1,
        "vegetation_season_end_month": 4,
        "max_custom_rotation_crops": 4,
        "crop_water_need_medium_index": 3.0,
        "crop_water_need_high_index": 4.5,
        "observation_window_months": 2,
        "soil_moisture_dry_m3_m3": 0.12,
        "soil_moisture_wet_m3_m3": 0.25,
    }
    values.update(overrides)
    return ThresholdsConfig.model_validate(values)


@pytest.fixture
def client() -> Iterator:
    from fastapi.testclient import TestClient

    from spaceapps_core.main import create_app

    with TestClient(create_app()) as c:
        yield c
