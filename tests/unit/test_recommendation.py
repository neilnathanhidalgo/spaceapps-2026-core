from __future__ import annotations

from datetime import date

import httpx
import pytest
import respx
from pydantic import ValidationError

from spaceapps_core.core.errors import InvalidRequestError, NotConfiguredError
from spaceapps_core.schemas.recommendation import (
    RecommendationRequest,
    SoilMoistureState,
    SoilProfile,
    VegetationTrend,
)
from spaceapps_core.services.agro_config import load_agro_config, parse_agro_config
from spaceapps_core.services.app_catalog import build_catalog
from spaceapps_core.services.et0 import extraterrestrial_radiation, reference_et0
from spaceapps_core.services.recent_rain import ObservedRain
from spaceapps_core.services.recommendation import (
    MonthlyWeather,
    RankingInput,
    add_months,
    average_monthly_weather,
    build_recommendation,
    calendar_risk_months,
    climate_risk_level,
    crop_windows,
    current_soil_score,
    long_term_plan,
    month_waters,
    monthly_et0,
    rank_options,
    repeated_crops,
    risky_months_of_year,
    rule_warnings,
    soil_impact_of,
)

POWER_DAILY_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
SOILGRIDS_URL = "https://rest.isric.org/soilgrids/v2.0/properties/query"
ORNL_URL = "https://modis.ornl.gov/rst/api/v1/MOD13Q1/subset"
PILOT = {"lat": -5.19, "lon": -80.63}


def _crop(
    crop_id: str,
    kc: list[float],
    soil_impact: str,
    *,
    fixes_nitrogen: bool = False,
    family: str | None = None,
    planting_months: list[int] | None = None,
) -> dict:
    return {
        "id": crop_id,
        "name": crop_id.title(),
        "family": family or crop_id,
        "planting_months": planting_months or list(range(1, 13)),
        "kc_by_month": kc,
        "soil_impact": soil_impact,
        "fixes_nitrogen": fixes_nitrogen,
        "rationale": f"rationale {crop_id}",
        "evidence": f"evidence {crop_id}",
        "benefits": f"benefits {crop_id}",
        "unknowns": f"unknowns {crop_id}",
        "risks": f"risks {crop_id}",
        "planting_instructions": f"instructions {crop_id}",
    }


def _config_dict(**overrides: object) -> dict:
    config = {
        "crops": [
            _crop("rice", [1.0, 1.1, 1.2], "degrades"),
            _crop("maize", [0.5, 1.0], "neutral"),
            _crop("bean", [0.5, 0.9], "improves_a_lot", fixes_nitrogen=True),
            _crop("cotton", [0.4, 0.8, 1.1], "improves"),
        ],
        "rotations": [
            {"id": "r1", "crop_ids": ["maize", "bean"]},
            {"id": "r2", "crop_ids": ["cotton", "bean"]},
            {"id": "r3", "crop_ids": ["bean", "maize"]},
        ],
        "scenarios": {"heavy_rains": [2017], "normal": [2019], "dry": [2004]},
        "thresholds": {
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
            "effective_rain_fraction_by_texture": {"sandy": 0.5},
            "soil_organic_carbon_low_g_kg": 10.0,
            "soil_organic_carbon_high_g_kg": 20.0,
            "soil_vegetation_decline_penalty": 1,
            "vegetation_trend_years": 5,
            "vegetation_flat_tolerance": 0.05,
            "vegetation_season_start_month": 1,
            "vegetation_season_end_month": 4,
            "max_custom_rotation_crops": 3,
            "crop_water_need_medium_index": 2.0,
            "crop_water_need_high_index": 3.0,
            "observation_window_months": 2,
            "soil_moisture_dry_m3_m3": 0.12,
            "soil_moisture_wet_m3_m3": 0.25,
        },
        "soil_textures": [
            {"id": "sandy", "name": "Arenosa", "description": "Se desarma en la mano."},
            {"id": "loamy", "name": "Franca", "description": "Se hace bola y se rompe."},
            {"id": "clayey", "name": "Arcillosa", "description": "Se pega en la mano."},
        ],
        "priorities": [
            {
                "id": "save-water",
                "name": "Cuidar mi agua",
                "phrase": "cuidar tu agua",
                "criterion": "least_water",
            },
            {
                "id": "restore-soil",
                "name": "Recuperar mi tierra",
                "phrase": "recuperar tu tierra",
                "criterion": "most_soil_improvement",
            },
            {
                "id": "lower-climate-risk",
                "name": "Menos riesgo de clima",
                "phrase": "tener menos riesgo",
                "criterion": "least_climate_risk",
            },
        ],
        "restrictions": [
            {"id": "no-cotton-buyer", "name": "Sin comprador", "excludes_crop_ids": ["cotton"]},
            {
                "id": "low-water",
                "name": "Poca agua",
                "excludes_crop_ids": [],
                "excludes_high_water_use": True,
            },
        ],
        "defaults": {"last_crop_id": "rice", "current_practice_campaigns": 2},
        "content": {
            "irrigation_source": "Poechos",
            "soil_texture_question": "¿A cuál se parece tu tierra?",
            "scenario_notes": {"heavy_rains": "A, ", "normal": "B, ", "dry": "C, "},
            "repeat_warnings": {"heavy_rains": "A", "normal": "B", "dry": "C"},
            "soil_findings": ["Lleva {campaigns} campañas seguidas de {crop}."],
            "same_family_warning": "{first} y {second}: {family}",
            "planting_month_warning": "{crop} en {month}, no en {months}",
            "soil_texture_findings": {"sandy": "Tierra arenosa ({sand}% de arena)."},
            "soil_reported_texture_findings": {"clayey": "Nos dijiste que es arcillosa."},
            "soil_moisture_findings": {"dry": "Tierra seca en {days} días ({moisture})."},
            "recent_rain_findings": {"dry": "Llovieron {total} mm en {days} días: año seco."},
            "soil_carbon_findings": {"normal": "Materia orgánica media ({carbon} g/kg)."},
            "vegetation_findings": {"down": "El verdor bajó {percent} desde {start_year}."},
        },
    }
    config.update(overrides)
    return config


def _climate(rain_by_month: list[float], *, t2m_max: float = 32.0, t2m_min: float = 20.0) -> dict:
    return {
        month: MonthlyWeather(rain_mm=rain, t2m_max=t2m_max, t2m_min=t2m_min)
        for month, rain in enumerate(rain_by_month, start=1)
    }


DRY_YEAR = _climate([10] * 12)
WET_YEAR = _climate([10, 200, 300, 10, 10, 10, 10, 10, 10, 10, 10, 10])
CLIMATES = {"heavy_rains": WET_YEAR, "normal": DRY_YEAR, "dry": DRY_YEAR}


def test_extraterrestrial_radiation_matches_fao56_example() -> None:
    # FAO-56, example 8: latitude 20 degS, 3 September (day 246) -> 32.2 MJ/m2/day.
    assert extraterrestrial_radiation(-20.0, 246) == pytest.approx(32.2, abs=0.05)


def test_reference_et0_hargreaves() -> None:
    radiation_mm = 0.408 * extraterrestrial_radiation(-5.19, 349)
    expected = 0.0023 * radiation_mm * (24 + 17.8) * 12**0.5

    assert reference_et0(
        t2m_max=30.0, t2m_min=18.0, latitude=-5.19, day_of_year=349
    ) == pytest.approx(expected)


def test_reference_et0_never_negative_with_inverted_temperatures() -> None:
    assert reference_et0(t2m_max=20.0, t2m_min=30.0, latitude=-5.19, day_of_year=1) == 0.0


def test_monthly_et0_grows_with_temperature_spread() -> None:
    narrow = monthly_et0(_climate([5] * 12, t2m_max=30.0, t2m_min=26.0), -5.19)
    wide = monthly_et0(_climate([5] * 12, t2m_max=34.0, t2m_min=22.0), -5.19)

    assert wide[1] > narrow[1]


def test_average_monthly_weather_averages_totals_across_years() -> None:
    config = parse_agro_config(_config_dict())
    series = _power_series([2017, 2019], rain_mm={2017: 4.0, 2019: 2.0})

    climate = average_monthly_weather(series, config.scenarios.years_for("heavy_rains"))
    both = average_monthly_weather(series, [2017, 2019])

    assert climate[1].rain_mm == pytest.approx(31 * 4.0)
    assert both[1].rain_mm == pytest.approx(31 * 3.0)
    assert both[1].t2m_max == pytest.approx(32.0)
    assert both[1].t2m_min == pytest.approx(20.0)


def test_crop_windows_chain_one_after_the_other() -> None:
    config = parse_agro_config(_config_dict())
    crops = [config.crop("maize"), config.crop("bean")]

    windows = crop_windows(date(2026, 12, 15), crops)

    assert [(window.crop.id, window.start, window.month_count) for window in windows] == [
        ("maize", date(2026, 12, 1), 2),
        ("bean", date(2027, 2, 1), 2),
    ]


def test_add_months_crosses_the_year() -> None:
    assert add_months(date(2026, 12, 1), 1) == date(2027, 1, 1)
    assert add_months(date(2026, 12, 1), 13) == date(2028, 1, 1)


def test_month_waters_discounts_effective_rain_and_scales_with_area() -> None:
    config = parse_agro_config(_config_dict())
    windows = crop_windows(date(2026, 12, 1), [config.crop("maize")])
    climate = _climate([100.0] * 12)
    climate[1] = MonthlyWeather(rain_mm=1000.0, t2m_max=32.0, t2m_min=20.0)

    waters = month_waters(
        windows,
        climate,
        dict.fromkeys(range(1, 13), 5.0),
        area_ha=2.0,
        effective_rain_fraction=0.8,
    )

    # December: 5 mm/day x kc 0.5 x 31 days = 77.5 mm, minus 80 mm of
    # effective rain -> nothing to irrigate.
    assert waters[0].irrigation_mm == 0.0
    # January: 5 mm/day x kc 1.0 x 31 days = 155 mm, minus 800 mm -> 0 again.
    assert waters[1].irrigation_mm == 0.0

    drier = _climate([10.0] * 12)
    waters = month_waters(
        windows,
        drier,
        dict.fromkeys(range(1, 13), 5.0),
        area_ha=2.0,
        effective_rain_fraction=0.8,
    )

    assert waters[0].irrigation_mm == pytest.approx(5 * 0.5 * 31 - 8)
    assert waters[0].irrigation_m3 == pytest.approx((5 * 0.5 * 31 - 8) * 2 * 10)
    assert waters[1].irrigation_mm == pytest.approx(5 * 1.0 * 31 - 8)


def test_risk_months_are_the_calendar_months_above_the_threshold() -> None:
    config = parse_agro_config(_config_dict())
    windows = crop_windows(date(2026, 12, 1), [config.crop("maize"), config.crop("bean")])

    risky = risky_months_of_year(WET_YEAR, config.thresholds.risk_month_rain_mm)

    assert risky == {2, 3}
    assert calendar_risk_months(windows, risky) == [date(2027, 2, 1), date(2027, 3, 1)]
    assert calendar_risk_months(windows, risky_months_of_year(DRY_YEAR, 150.0)) == []


def test_climate_risk_level_follows_the_thresholds() -> None:
    thresholds = parse_agro_config(_config_dict()).thresholds

    assert climate_risk_level(0, thresholds) == "low"
    assert climate_risk_level(1, thresholds) == "medium"
    assert climate_risk_level(2, thresholds) == "high"


def test_current_soil_score_ignores_the_tolerated_campaigns() -> None:
    config = parse_agro_config(_config_dict())
    thresholds = config.thresholds
    rice, bean = config.crop("rice"), config.crop("bean")

    assert current_soil_score(rice, 1, thresholds) == 3
    assert current_soil_score(rice, 3, thresholds) == 1
    assert current_soil_score(rice, 9, thresholds) == 0
    assert current_soil_score(bean, 3, thresholds) == 3


def test_soil_impact_of_a_rotation_combines_its_crops() -> None:
    config = parse_agro_config(_config_dict())

    assert soil_impact_of([config.crop("rice")]) == ("degrades", -1)
    assert soil_impact_of([config.crop("maize")]) == ("neutral", 0)
    assert soil_impact_of([config.crop("cotton")]) == ("improves", 1)
    assert soil_impact_of([config.crop("maize"), config.crop("bean")]) == ("improves_a_lot", 2)


def test_long_term_plan_repeats_the_rotation_within_the_horizon() -> None:
    config = parse_agro_config(_config_dict())
    crops = [config.crop("rice")]

    assert len(repeated_crops(crops, 24)) == 8
    plan = long_term_plan(date(2026, 12, 15), crops, 3, 24)

    assert plan[0].start == date(2026, 12, 1)
    assert plan[0].end == date(2027, 2, 1)
    assert plan[0].soil_after == "regular"
    assert plan[-1].soil_after == "very_tired"


def test_rank_options_per_priority() -> None:
    thirsty_and_safe = RankingInput(
        option_id="thirsty", irrigation_m3=9000, risk_month_count=0, soil_impact_score=0
    )
    frugal_and_risky = RankingInput(
        option_id="frugal", irrigation_m3=3000, risk_month_count=2, soil_impact_score=1
    )
    restorative = RankingInput(
        option_id="restorative", irrigation_m3=5000, risk_month_count=1, soil_impact_score=3
    )
    options = [thirsty_and_safe, frugal_and_risky, restorative]

    assert rank_options(options, "least_water") == ["frugal", "restorative", "thirsty"]
    assert rank_options(options, "least_climate_risk") == ["thirsty", "restorative", "frugal"]
    assert rank_options(options, "most_soil_improvement") == [
        "restorative",
        "frugal",
        "thirsty",
    ]


def test_rank_options_keeps_the_catalog_order_on_ties() -> None:
    options = [
        RankingInput(option_id="a", irrigation_m3=100, risk_month_count=1, soil_impact_score=2),
        RankingInput(option_id="b", irrigation_m3=100, risk_month_count=1, soil_impact_score=2),
    ]

    assert rank_options(options, "least_water") == ["a", "b"]
    assert rank_options(options, "most_soil_improvement") == ["a", "b"]


def _request(**overrides: object) -> RecommendationRequest:
    payload = {
        "lat": -5.19,
        "lon": -80.63,
        "area_ha": 2.0,
        "planting_date": date(2026, 12, 15),
        "last_crop_id": "rice",
        "consecutive_campaigns": 3,
        "priority_id": "save-water",
        "restriction_ids": ["low-water"],
    }
    payload.update(overrides)
    return RecommendationRequest.model_validate(payload)


def test_build_recommendation_covers_the_three_scenarios() -> None:
    config = parse_agro_config(_config_dict())

    response = build_recommendation(_request(), config, CLIMATES)

    assert [option.id for option in response.options] == ["r1", "r2", "r3"]
    assert set(response.ranking) == {"save-water", "restore-soil", "lower-climate-risk"}
    assert set(response.ranking["save-water"]) == {"heavy_rains", "normal", "dry"}
    assert response.soil_health.condition == "tired"
    assert response.soil_health.findings == ["Lleva 3 campañas seguidas de rice."]
    assert response.current_practice.crop_ids == ["rice", "rice"]
    assert response.current_practice.soil_in_two_years == "very_tired"
    assert response.risk_months["heavy_rains"] == [date(2027, 2, 1), date(2027, 3, 1)]
    assert response.risk_months["dry"] == []
    assert response.climate_basis.reference_years["heavy_rains"] == [2017]
    assert response.example_parameters is False

    r1 = response.options[0]
    assert r1.scenarios["heavy_rains"].climate_risk == "high"
    assert r1.scenarios["normal"].climate_risk == "low"
    assert r1.calendar.timeline_months == 4
    assert r1.factsheet.rationale == "rationale maize rationale bean"


def test_build_recommendation_ranks_every_priority_of_the_catalog() -> None:
    config = parse_agro_config(_config_dict())

    response = build_recommendation(_request(priority_id="save-water"), config, CLIMATES)

    waters = {option.id: option.scenarios["normal"].irrigation_m3 for option in response.options}
    assert response.ranking["save-water"]["normal"] == sorted(waters, key=lambda id_: waters[id_])
    # r2 is the only rotation whose crops add up to 3 points of soil impact.
    assert response.ranking["restore-soil"]["normal"][0] == "r2"
    # Every option hits the same two risk months, so water breaks the tie.
    assert response.ranking["lower-climate-risk"]["heavy_rains"] == ["r3", "r1", "r2"]


def test_build_recommendation_marks_restrictions_without_dropping_options() -> None:
    config = parse_agro_config(_config_dict())

    response = build_recommendation(_request(), config, CLIMATES)
    excluded = {option.id: option.excluded_by for option in response.options}

    assert excluded["r1"] == []
    assert "no-cotton-buyer" in excluded["r2"]
    assert len(response.options) == 3


def test_build_recommendation_excludes_thirsty_options_with_low_water() -> None:
    config = parse_agro_config(
        _config_dict(
            thresholds={
                **_config_dict()["thresholds"],  # type: ignore[dict-item]
                "low_water_m3_per_ha": 1.0,
            }
        )
    )

    response = build_recommendation(_request(), config, CLIMATES)

    assert all("low-water" in option.excluded_by for option in response.options)


SANDY_SOIL = SoilProfile(
    sand_percent=79.3,
    clay_percent=7.0,
    organic_carbon_g_kg=13.5,
    texture="sandy",
    depth="0-5cm",
)
FALLING_GREENNESS = VegetationTrend(
    start_year=2021,
    end_year=2026,
    start_ndvi=0.42,
    end_ndvi=0.34,
    change_ratio=-0.19,
    direction="down",
)
DRY_TOPSOIL = SoilMoistureState(
    mean_m3_m3=0.08,
    band="dry",
    start=date(2026, 9, 1),
    end=date(2026, 10, 31),
    observed_days=42,
)
FEBRUARY_RAIN = ObservedRain(
    total_mm=12.0,
    observed_days=28,
    start=date(2027, 2, 1),
    end=date(2027, 2, 28),
    days_by_month={2: 28},
)


def test_local_soil_raises_the_irrigation_and_tires_the_soil() -> None:
    config = parse_agro_config(_config_dict())

    without = build_recommendation(_request(), config, CLIMATES)
    with_soil = build_recommendation(
        _request(), config, CLIMATES, soil=SANDY_SOIL, vegetation=FALLING_GREENNESS
    )

    # Un suelo arenoso aprovecha menos la lluvia, así que hay que regar más.
    assert (
        with_soil.options[0].scenarios["normal"].irrigation_m3
        > without.options[0].scenarios["normal"].irrigation_m3
    )
    assert with_soil.climate_basis.effective_rain_fraction == 0.5
    assert without.soil_health.condition == "tired"
    assert with_soil.soil_health.condition == "very_tired"
    assert with_soil.data_sources == ["nasa_power", "soilgrids", "ornl_modis"]
    assert without.data_sources == ["nasa_power"]


def test_soil_findings_explain_texture_carbon_and_greenness() -> None:
    config = parse_agro_config(_config_dict())

    response = build_recommendation(
        _request(), config, CLIMATES, soil=SANDY_SOIL, vegetation=FALLING_GREENNESS
    )

    assert response.soil_health.findings == [
        "Lleva 3 campañas seguidas de rice.",
        "Tierra arenosa (79% de arena).",
        "Materia orgánica media (13.5 g/kg).",
        "El verdor bajó 19% desde 2021.",
    ]
    assert response.soil_health.profile == SANDY_SOIL
    assert response.soil_health.vegetation_trend == FALLING_GREENNESS


def test_the_farmer_texture_wins_over_soilgrids() -> None:
    config = parse_agro_config(_config_dict())

    measured = build_recommendation(_request(), config, CLIMATES, soil=SANDY_SOIL)
    reported = build_recommendation(
        _request(reported_soil_texture="clayey"), config, CLIMATES, soil=SANDY_SOIL
    )

    assert measured.soil_health.texture_source == "soilgrids"
    assert reported.soil_health.texture_source == "farmer"
    assert reported.soil_health.texture == "clayey"
    # El perfil de SoilGrids se sigue entregando tal cual: solo cambia quién
    # manda en el cálculo.
    assert reported.soil_health.profile == SANDY_SOIL
    # Sin fracción para "clayey" se usa la global (0.8), que aprovecha más la
    # lluvia que la arenosa (0.5), así que hay que regar menos.
    assert reported.climate_basis.effective_rain_fraction == 0.8
    assert (
        reported.options[0].scenarios["heavy_rains"].irrigation_m3
        < measured.options[0].scenarios["heavy_rains"].irrigation_m3
    )
    assert "Nos dijiste que es arcillosa." in reported.soil_health.findings
    assert not any("arenosa" in finding for finding in reported.soil_health.findings)
    assert reported.data_sources == ["nasa_power", "soilgrids", "farmer"]


def test_catalog_crops_carry_water_duration_and_nitrogen() -> None:
    catalog = build_catalog(parse_agro_config(_config_dict()))
    crops = {crop.id: crop for crop in catalog.crops}

    assert crops["rice"].water_index == 3.3
    assert crops["rice"].water_need == "high"
    assert crops["cotton"].water_need == "medium"
    assert crops["maize"].water_need == "low"
    assert crops["rice"].cycle_months == 3
    assert crops["bean"].fixes_nitrogen is True
    assert crops["rice"].fixes_nitrogen is False
    assert [texture.id for texture in catalog.soil_textures] == ["sandy", "loamy", "clayey"]
    assert catalog.soil_texture_question


def test_measured_water_is_reported_without_moving_the_irrigation() -> None:
    config = parse_agro_config(_config_dict())
    climates = {
        "heavy_rains": _climate([10, 200] + [10] * 10),
        "normal": _climate([50] * 12),
        "dry": _climate([10] * 12),
    }

    without = build_recommendation(_request(), config, climates)
    with_observations = build_recommendation(
        _request(),
        config,
        climates,
        soil_moisture=DRY_TOPSOIL,
        recent_rain=FEBRUARY_RAIN,
    )

    # SMAP mide los primeros 5 cm, no el agua de las raíces: se informa, no
    # se mete en el balance de riego (decisión documentada en el README).
    assert (
        with_observations.options[0].scenarios["normal"].irrigation_m3
        == without.options[0].scenarios["normal"].irrigation_m3
    )
    assert with_observations.soil_health.soil_moisture == DRY_TOPSOIL
    assert "Tierra seca en 42 días (0.08)." in with_observations.soil_health.findings

    rain = with_observations.recent_rain
    assert rain is not None
    # 12 mm medidos contra 200 / 50 / 10 esperados: el año va como uno seco.
    assert rain.scenario_totals == {"heavy_rains": 200.0, "normal": 50.0, "dry": 10.0}
    assert rain.closest_scenario == "dry"
    assert rain.finding == "Llovieron 12.0 mm en 28 días: año seco."
    assert with_observations.data_sources == ["nasa_power", "smap", "gpm_imerg"]
    assert without.recent_rain is None
    assert without.soil_health.soil_moisture is None


def test_custom_rotation_comes_back_as_one_more_option() -> None:
    config = parse_agro_config(_config_dict())

    response = build_recommendation(
        _request(custom_rotation=["rice", "bean", "maize"]), config, CLIMATES
    )
    custom = next(option for option in response.options if option.id == "custom")

    assert [option.id for option in response.options] == ["r1", "r2", "r3", "custom"]
    assert custom.crop_ids == ["rice", "bean", "maize"]
    assert custom.cycle_months == 7
    assert custom.calendar.periods[0].crop_id == "rice"
    # El arroz resta y el frejol suma: la secuencia mejora, pero menos.
    assert custom.soil_impact == "improves"
    assert set(custom.scenarios) == {"heavy_rains", "normal", "dry"}
    assert "custom" in response.ranking["save-water"]["normal"]


def test_custom_rotation_is_validated() -> None:
    config = parse_agro_config(_config_dict())

    with pytest.raises(InvalidRequestError):
        build_recommendation(_request(custom_rotation=["quinoa"]), config, CLIMATES)
    with pytest.raises(InvalidRequestError):
        build_recommendation(
            _request(custom_rotation=["rice", "bean", "maize", "cotton"]), config, CLIMATES
        )


def test_config_reserves_the_custom_rotation_id() -> None:
    broken = _config_dict(rotations=[{"id": "custom", "crop_ids": ["maize"]}])

    with pytest.raises(ValidationError):
        parse_agro_config(broken)


def test_build_recommendation_rejects_unknown_ids() -> None:
    config = parse_agro_config(_config_dict())

    with pytest.raises(InvalidRequestError):
        build_recommendation(_request(priority_id="ganar-mas"), config, CLIMATES)
    with pytest.raises(InvalidRequestError):
        build_recommendation(_request(restriction_ids=["sin-tractor"]), config, CLIMATES)
    with pytest.raises(InvalidRequestError):
        build_recommendation(_request(last_crop_id="quinoa"), config, CLIMATES)


def test_agro_config_rejects_rotations_with_unknown_crops(tmp_path) -> None:
    import json

    broken = _config_dict(rotations=[{"id": "r1", "crop_ids": ["quinoa"]}])
    path = tmp_path / "agro_config.json"
    path.write_text(json.dumps(broken), encoding="utf-8")

    with pytest.raises(NotConfiguredError):
        load_agro_config(str(path))


def test_packaged_config_is_valid_and_flagged_as_example() -> None:
    config = load_agro_config()

    assert config.example_parameters is True
    assert {priority.id for priority in config.priorities} == {
        "save-water",
        "restore-soil",
        "lower-climate-risk",
    }


def _power_series(years: list[int], *, rain_mm: dict[int, float]) -> list:
    from spaceapps_core.clients.power import PowerClient
    from spaceapps_core.schemas.common import Location

    client = PowerClient()
    location = Location(**PILOT)
    return [
        one
        for year in years
        for one in client._parse_point_response(
            _power_payload(year, rain_mm[year]), location, _climate_variables()
        )
    ]


def _climate_variables() -> list:
    from spaceapps_core.services.recommendation import CLIMATE_VARIABLES

    return list(CLIMATE_VARIABLES)


def _power_payload(year: int, rain_mm: float) -> dict:
    days = [
        date(year, month, day).strftime("%Y%m%d") for month in range(1, 13) for day in range(1, 29)
    ]
    days += [date(year, 1, day).strftime("%Y%m%d") for day in (29, 30, 31)]
    return {
        "properties": {
            "parameter": {
                "PRECTOTCORR": dict.fromkeys(days, rain_mm),
                "T2M_MAX": dict.fromkeys(days, 32.0),
                "T2M_MIN": dict.fromkeys(days, 20.0),
            }
        },
        "parameters": {},
    }


def test_catalog_endpoint(client) -> None:
    r = client.get("/api/v1/app/catalog")

    assert r.status_code == 200
    data = r.json()
    assert data["example_parameters"] is True
    assert data["priorities"][0]["id"] == "lower-climate-risk"
    assert {crop["id"] for crop in data["crops"]} >= {"rice", "maize", "bean"}
    assert all(crop["cycle_months"] >= 1 for crop in data["crops"])
    assert data["max_rotation_crops"] >= 2
    assert {texture["id"] for texture in data["soil_textures"]} == {
        "sandy",
        "loamy",
        "clayey",
    }
    assert data["soil_texture_question"]
    assert {crop["id"] for crop in data["crops"] if crop["fixes_nitrogen"]} == {"bean", "pulse"}


def _soilgrids_payload() -> dict:
    def layer(name: str, mean: float | None) -> dict:
        return {
            "name": name,
            "unit_measure": {"d_factor": 10},
            "depths": [{"label": "0-5cm", "values": {"mean": mean}}],
        }

    return {"properties": {"layers": [layer("sand", 793), layer("clay", 70), layer("soc", 135)]}}


def _ndvi_payload(request: httpx.Request) -> httpx.Response:
    year = request.url.params["startDate"][1:5]
    value = 5000 if year == "2021" else 4000
    return httpx.Response(
        200,
        json={
            "scale": "0.0001",
            "subset": [{"calendar_date": f"{year}-02-01", "data": [value]}],
        },
    )


def _mock_upstreams(mock: respx.MockRouter) -> None:
    def power(request: httpx.Request) -> httpx.Response:
        year = int(request.url.params["start"][:4])
        rain = 20.0 if year in (1998, 2017, 2023) else 1.0
        return httpx.Response(200, json=_power_payload(year, rain))

    mock.get(POWER_DAILY_URL).mock(side_effect=power)
    mock.get(SOILGRIDS_URL).mock(return_value=httpx.Response(200, json=_soilgrids_payload()))
    mock.get(ORNL_URL).mock(side_effect=_ndvi_payload)


def test_recommendation_endpoint(client) -> None:
    body = {
        **PILOT,
        "area_ha": 2.0,
        "planting_date": "2026-12-15",
        "last_crop_id": "rice",
        "consecutive_campaigns": 3,
        "priority_id": "save-water",
        "restriction_ids": ["low-water"],
        "custom_rotation": ["rice", "bean", "maize"],
    }
    with respx.mock(assert_all_called=True) as mock:
        _mock_upstreams(mock)
        r = client.post("/api/v1/app/recommendation", json=body)

    assert r.status_code == 200
    data = r.json()
    assert data["priority_id"] == "save-water"
    assert data["example_parameters"] is True
    assert data["irrigation_source"]
    assert set(data["ranking"]) == {"save-water", "restore-soil", "lower-climate-risk"}
    assert sorted(data["ranking"]["save-water"]["normal"]) == sorted(
        option["id"] for option in data["options"]
    )
    assert {crop["id"] for crop in data["crops"]} >= {"rice", "maize"}
    # El verdor no se espera: la primera respuesta no lo trae y la tarea de
    # fondo deja las ventanas de NDVI en caché.
    assert data["data_sources"] == ["nasa_power", "soilgrids"]
    assert data["soil_health"]["profile"]["texture"] == "sandy"
    assert data["soil_health"]["vegetation_trend"] is None
    assert [option["id"] for option in data["options"]][-1] == "custom"
    assert data["climate_basis"]["source"] == "nasa_power"
    assert len(data["climate_basis"]["monthly_climate"]["normal"]) == 12

    option = data["options"][0]
    assert set(option["scenarios"]) == {"heavy_rains", "normal", "dry"}
    assert option["scenarios"]["normal"]["irrigation_m3"] > 0
    assert option["calendar"]["timeline_start"] == "2026-12-01"
    assert option["calendar"]["periods"][0]["crop_id"] == option["crop_ids"][0]
    assert data["current_practice"]["crop_ids"][0] == "rice"
    # Heavy rains leave less to irrigate than a dry year.
    assert (
        option["scenarios"]["heavy_rains"]["irrigation_m3"]
        < option["scenarios"]["dry"]["irrigation_m3"]
    )


def test_recommendation_endpoint_rejects_unknown_priority(client) -> None:
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(POWER_DAILY_URL).mock(return_value=httpx.Response(200, json={}))
        r = client.post(
            "/api/v1/app/recommendation",
            json={**PILOT, "planting_date": "2026-12-15", "priority_id": "maximize-profit"},
        )

    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid_request"
    assert not route.called


def test_recommendation_endpoint_forbids_extra_fields(client) -> None:
    r = client.post(
        "/api/v1/app/recommendation",
        json={**PILOT, "planting_date": "2026-12-15", "expected_profit": 3000},
    )

    assert r.status_code == 422


def test_recommendation_endpoint_survives_soil_and_ndvi_outages(client) -> None:
    with respx.mock(assert_all_called=True) as mock:
        _mock_upstreams(mock)
        mock.get(SOILGRIDS_URL).mock(return_value=httpx.Response(400, text="masked pixel"))
        mock.get(ORNL_URL).mock(return_value=httpx.Response(400, text="no product"))
        r = client.post(
            "/api/v1/app/recommendation",
            json={**PILOT, "planting_date": "2026-12-15"},
        )

    assert r.status_code == 200
    data = r.json()
    assert data["data_sources"] == ["nasa_power"]
    assert data["soil_health"]["profile"] is None
    assert data["soil_health"]["vegetation_trend"] is None


def test_recommendation_endpoint_rejects_an_unknown_custom_crop(client) -> None:
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(POWER_DAILY_URL).mock(return_value=httpx.Response(200, json={}))
        r = client.post(
            "/api/v1/app/recommendation",
            json={
                **PILOT,
                "planting_date": "2026-12-15",
                "custom_rotation": ["rice", "quinoa"],
            },
        )

    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid_request"
    assert not route.called


def test_recommendation_endpoint_adds_the_greenness_once_warm(client) -> None:
    body = {**PILOT, "planting_date": "2026-12-15"}
    with respx.mock(assert_all_called=True) as mock:
        _mock_upstreams(mock)
        first = client.post("/api/v1/app/recommendation", json=body).json()
        second = client.post("/api/v1/app/recommendation", json=body).json()

    assert first["soil_health"]["vegetation_trend"] is None
    trend = second["soil_health"]["vegetation_trend"]
    assert trend["direction"] == "down"
    assert trend["start_year"] == 2021
    assert second["data_sources"] == ["nasa_power", "soilgrids", "ornl_modis"]
    assert any("verdor" in finding for finding in second["soil_health"]["findings"])


def test_same_family_in_a_row_warns_and_is_never_low_risk() -> None:
    config = parse_agro_config(_config_dict())
    request = RecommendationRequest(
        **PILOT, planting_date=date(2026, 12, 1), custom_rotation=["rice", "rice"]
    )

    response = build_recommendation(request, config, CLIMATES)
    custom = next(option for option in response.options if option.id == "custom")

    assert custom.warnings == ["rice y rice: rice"]
    assert {result.climate_risk for result in custom.scenarios.values()} <= {"medium", "high"}
    assert response.current_practice.warnings == ["rice y rice: rice"]


def test_family_rule_looks_at_the_restart_of_the_rotation() -> None:
    crops = [
        _crop("maize", [0.5, 1.0], "neutral", family="Poaceae"),
        _crop("bean", [0.5, 0.9], "improves_a_lot", family="Fabaceae"),
        _crop("rice", [1.0, 1.1, 1.2], "degrades", family="Poaceae"),
    ]
    config = parse_agro_config(
        _config_dict(
            crops=crops,
            rotations=[{"id": "r1", "crop_ids": ["maize", "bean", "rice"]}],
            restrictions=[],
        )
    )

    warnings = rule_warnings(
        date(2026, 12, 1),
        [config.crop("maize"), config.crop("bean"), config.crop("rice")],
        24,
        config.content,
    )

    assert warnings == ["rice y maize: Poaceae"]


def test_planting_outside_the_usual_months_warns() -> None:
    crops = [
        _crop("maize", [0.5, 1.0], "neutral", family="Poaceae", planting_months=[4, 5]),
        _crop("bean", [0.5, 0.9], "improves_a_lot", family="Fabaceae", planting_months=[2]),
    ]
    config = parse_agro_config(
        _config_dict(
            crops=crops,
            rotations=[{"id": "r1", "crop_ids": ["maize", "bean"]}],
            restrictions=[],
            defaults={"last_crop_id": "maize", "current_practice_campaigns": 1},
        )
    )

    warnings = rule_warnings(
        date(2026, 12, 1), [config.crop("maize"), config.crop("bean")], 4, config.content
    )

    assert warnings == ["maize en diciembre, no en abril o mayo"]


def test_a_rotation_without_broken_rules_keeps_its_climate_risk() -> None:
    config = parse_agro_config(_config_dict())
    request = RecommendationRequest(**PILOT, planting_date=date(2026, 12, 1))

    response = build_recommendation(request, config, CLIMATES)

    assert all(option.warnings == [] for option in response.options)


def test_packaged_config_rotations_never_repeat_a_family() -> None:
    config = load_agro_config()
    for rotation in config.rotations:
        crops = [config.crop(crop_id) for crop_id in rotation.crop_ids]
        pairs = zip(crops, crops[1:] + crops[:1], strict=True)
        assert all(first.family != second.family for first, second in pairs), rotation.id
