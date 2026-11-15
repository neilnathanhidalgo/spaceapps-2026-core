from __future__ import annotations

from datetime import date

import httpx
import respx

from spaceapps_core.clients.appeears import (
    APPEEARS_BASE_URL,
    SMAP_SOIL_MOISTURE_LAYERS,
)
from spaceapps_core.core.cache import get_cache, make_key
from spaceapps_core.schemas.common import Location, TimePoint, TimeSeries
from spaceapps_core.schemas.variables import CanonicalVariable
from spaceapps_core.services.observations import observation_window
from spaceapps_core.services.recent_rain import (
    build_recent_rain,
    cached_recent_rain,
    closest_scenario,
    expected_totals,
    observed_rain,
    warm_recent_rain,
)
from spaceapps_core.services.soil_moisture import (
    cached_soil_moisture,
    moisture_band,
    soil_moisture_state,
    warm_soil_moisture,
)
from tests.conftest import agro_thresholds

PILOT = Location(lat=-5.19, lon=-80.63)
TODAY = date(2026, 11, 15)


def test_observation_window_covers_complete_months_only() -> None:
    assert observation_window(2, TODAY) == (date(2026, 9, 1), date(2026, 10, 31))
    assert observation_window(1, TODAY) == (date(2026, 10, 1), date(2026, 10, 31))
    # La ventana no se mueve dentro del mes: el punto sigue caliente en caché.
    assert observation_window(2, date(2026, 11, 2)) == observation_window(2, TODAY)
    assert observation_window(3, date(2027, 1, 5)) == (date(2026, 10, 1), date(2026, 12, 31))


def test_moisture_band_follows_the_thresholds() -> None:
    thresholds = agro_thresholds()

    assert moisture_band(0.05, thresholds) == "dry"
    assert moisture_band(0.12, thresholds) == "normal"
    assert moisture_band(0.25, thresholds) == "wet"


def test_soil_moisture_state_averages_the_measured_days() -> None:
    points = [
        {"date": "2026-09-01", "value": 0.10},
        {"date": "2026-09-02", "value": None},
        {"date": "2026-10-31", "value": 0.20},
    ]

    state = soil_moisture_state(points, agro_thresholds())

    assert state is not None
    assert state.mean_m3_m3 == 0.15
    assert state.band == "normal"
    assert state.observed_days == 2
    assert (state.start, state.end) == (date(2026, 9, 1), date(2026, 10, 31))
    assert soil_moisture_state([{"date": "2026-09-01", "value": None}], agro_thresholds()) is None


def test_cached_soil_moisture_reads_the_window_of_the_point() -> None:
    thresholds = agro_thresholds()
    start, end = observation_window(thresholds.observation_window_months, TODAY)
    assert cached_soil_moisture(PILOT, thresholds, today=TODAY) is None

    get_cache().set(
        make_key(
            "smap:points",
            {"lat": PILOT.lat, "lon": PILOT.lon, "start": start, "end": end},
        ),
        [{"date": "2026-09-01", "value": 0.3}],
    )

    state = cached_soil_moisture(PILOT, thresholds, today=TODAY)
    assert state is not None
    assert state.band == "wet"
    assert state.source == "smap"


async def test_warm_soil_moisture_does_nothing_without_credentials(monkeypatch) -> None:
    _without_credentials(monkeypatch)

    with respx.mock(assert_all_called=False) as mock:
        login = mock.post(f"{APPEEARS_BASE_URL}/login").mock(
            return_value=httpx.Response(200, json={"token": "t"})
        )
        await warm_soil_moisture(PILOT, today=TODAY)

    assert not login.called
    assert cached_soil_moisture(PILOT, agro_thresholds(), today=TODAY) is None


async def test_warm_soil_moisture_submits_the_job_and_then_stores_the_window(
    monkeypatch,
) -> None:
    _with_credentials(monkeypatch)
    column = SMAP_SOIL_MOISTURE_LAYERS[0].column_name()
    csv = f"Date,{column}\n2026-09-01,0.300\n2026-09-02,\n".encode()

    with respx.mock(assert_all_called=True) as mock:
        mock.post(f"{APPEEARS_BASE_URL}/login").mock(
            return_value=httpx.Response(200, json={"token": "t"})
        )
        submit = mock.post(f"{APPEEARS_BASE_URL}/task").mock(
            return_value=httpx.Response(200, json={"task_id": "task-1"})
        )
        mock.get(f"{APPEEARS_BASE_URL}/task/task-1").mock(
            side_effect=[
                httpx.Response(200, json={"status": "processing"}),
                httpx.Response(200, json={"status": "done"}),
            ]
        )
        mock.get(f"{APPEEARS_BASE_URL}/bundle/task-1").mock(
            return_value=httpx.Response(
                200, json={"files": [{"file_id": "f1", "file_name": "results.csv"}]}
            )
        )
        mock.get(f"{APPEEARS_BASE_URL}/bundle/task-1/f1").mock(
            return_value=httpx.Response(200, content=csv)
        )

        # Primera llamada: envía la tarea. Segunda: la encuentra corriendo.
        await warm_soil_moisture(PILOT, today=TODAY)
        assert cached_soil_moisture(PILOT, agro_thresholds(), today=TODAY) is None
        await warm_soil_moisture(PILOT, today=TODAY)
        assert cached_soil_moisture(PILOT, agro_thresholds(), today=TODAY) is None
        # Tercera: ya está lista y se guarda la ventana.
        await warm_soil_moisture(PILOT, today=TODAY)

    state = cached_soil_moisture(PILOT, agro_thresholds(), today=TODAY)
    assert state is not None
    assert state.mean_m3_m3 == 0.3
    assert state.observed_days == 1
    # La tarea se envía una sola vez por punto y ventana.
    assert submit.call_count == 1


def test_observed_rain_adds_up_the_measured_days() -> None:
    series = _rain_series(
        {
            date(2026, 9, 1): 5.0,
            date(2026, 9, 2): None,
            date(2026, 10, 1): 7.5,
            date(2026, 11, 1): 100.0,
        }
    )

    rain = observed_rain(series, date(2026, 9, 1), date(2026, 10, 31))

    assert rain is not None
    assert rain.total_mm == 12.5
    assert rain.observed_days == 2
    assert rain.days_by_month == {9: 1, 10: 1}
    assert (rain.start, rain.end) == (date(2026, 9, 1), date(2026, 10, 1))
    assert observed_rain(_rain_series({}), date(2026, 9, 1), date(2026, 10, 31)) is None


def test_expected_totals_prorate_the_month_by_measured_days() -> None:
    monthly = {
        "heavy_rains": {9: 30.0, 10: 60.0},
        "normal": {9: 3.0, 10: 6.0},
        "dry": {9: 0.0, 10: 0.0},
    }

    totals = expected_totals({9: 30, 10: 15}, monthly)

    # Septiembre completo (30/30) más medio octubre (15/31).
    assert totals == {"heavy_rains": 59.0, "normal": 5.9, "dry": 0.0}
    assert closest_scenario(6.0, totals) == "normal"
    # Un empate conserva el orden de los escenarios.
    assert closest_scenario(29.5, {"heavy_rains": 59.0, "normal": 0.0, "dry": 0.0}) == "heavy_rains"


def test_build_recent_rain_names_the_scenario_the_year_looks_like() -> None:
    content = _content({"dry": "Llovieron {total} mm en {days} días: año seco."})
    rain = observed_rain(
        _rain_series({date(2026, 9, 1): 1.0, date(2026, 9, 2): 1.5}),
        date(2026, 9, 1),
        date(2026, 10, 31),
    )
    assert rain is not None

    built = build_recent_rain(
        rain,
        {"heavy_rains": {9: 300.0}, "normal": {9: 60.0}, "dry": {9: 3.0}},
        content,
    )

    assert built.closest_scenario == "dry"
    assert built.finding == "Llovieron 2.5 mm en 2 días: año seco."
    assert built.source == "gpm_imerg"


def test_build_recent_rain_survives_a_missing_text() -> None:
    rain = observed_rain(
        _rain_series({date(2026, 9, 1): 1.0}), date(2026, 9, 1), date(2026, 10, 31)
    )
    assert rain is not None

    built = build_recent_rain(rain, {"heavy_rains": {}, "normal": {}, "dry": {}}, _content({}))

    assert built.finding == ""


def test_cached_recent_rain_reads_the_window_of_the_point() -> None:
    thresholds = agro_thresholds()
    start, end = observation_window(thresholds.observation_window_months, TODAY)
    assert cached_recent_rain(PILOT, thresholds, today=TODAY) is None

    get_cache().set(
        make_key(
            "earthdata:imerg_daily",
            {"lat": PILOT.lat, "lon": PILOT.lon, "start": start, "end": end},
        ),
        {"points": [{"date": "2026-09-01", "value": 4.0}]},
    )

    rain = cached_recent_rain(PILOT, thresholds, today=TODAY)
    assert rain is not None
    assert rain.total_mm == 4.0


async def test_warm_recent_rain_does_nothing_without_credentials(monkeypatch) -> None:
    _without_credentials(monkeypatch)

    await warm_recent_rain(PILOT, today=TODAY)

    assert cached_recent_rain(PILOT, agro_thresholds(), today=TODAY) is None


def _with_credentials(monkeypatch) -> None:
    _patch_credentials(monkeypatch, user="someone", password="secret")


def _without_credentials(monkeypatch) -> None:
    _patch_credentials(monkeypatch, user="", password="")


def _patch_credentials(monkeypatch, *, user: str, password: str) -> None:
    """Settings are cached, and every client reads its own copy."""
    from spaceapps_core.core.config import get_settings

    monkeypatch.setenv("EARTHDATA_USERNAME", user)
    monkeypatch.setenv("EARTHDATA_PASSWORD", password)
    get_settings.cache_clear()
    monkeypatch.addfinalizer(get_settings.cache_clear)


def _rain_series(values: dict[date, float | None]) -> TimeSeries:
    return TimeSeries(
        source="earthdata",
        variable=CanonicalVariable.PRECIPITATION,
        unit="mm/day",
        location=PILOT,
        temporal_resolution="daily",
        points=[TimePoint(date=day, value=value) for day, value in values.items()],
        metadata={},
    )


def _content(recent_rain_findings: dict[str, str]):
    from spaceapps_core.services.agro_config import ContentConfig

    return ContentConfig.model_validate(
        {
            "irrigation_source": "Poechos",
            "soil_texture_question": "¿A cuál se parece tu tierra?",
            "scenario_notes": {"heavy_rains": "a", "normal": "b", "dry": "c"},
            "repeat_warnings": {"heavy_rains": "a", "normal": "b", "dry": "c"},
            "soil_findings": [],
            "recent_rain_findings": recent_rain_findings,
        }
    )
