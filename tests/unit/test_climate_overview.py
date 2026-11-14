from __future__ import annotations

from datetime import date, timedelta

import httpx
import pytest
import respx

from spaceapps_core.schemas.climate_overview import DailyForecast
from spaceapps_core.services.climate_overview import (
    build_advice,
    classify_day,
    moisture_level,
    times_normal,
)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
POWER_DAILY_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
POWER_CLIMATOLOGY_URL = "https://power.larc.nasa.gov/api/temporal/climatology/point"
MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


@pytest.mark.parametrize(
    ("rain_mm", "code", "expected"),
    [
        (40.0, 95, "heavy_rain"),
        (12.0, 63, "moderate_rain"),
        (2.0, 61, "rain"),
        (0.0, 3, "cloudy"),
        (0.0, 0, "sunny"),
        (0.0, None, "sunny"),
    ],
)
def test_classify_day(rain_mm: float, code: float | None, expected: str) -> None:
    assert classify_day(rain_mm, code) == expected


def test_times_normal_bounds_and_noise() -> None:
    assert times_normal(90.0, 30.0) == 3.0
    assert times_normal(0.4, 0.0) == 1.0
    assert times_normal(0.0, 30.0) == 0.1
    assert times_normal(500.0, 2.0) == 10.0


def test_moisture_level_thresholds() -> None:
    assert moisture_level(-0.15) == "dry"
    assert moisture_level(0.05) == "normal"
    assert moisture_level(0.15) == "wet"
    assert moisture_level(0.3) == "very_wet"


def test_advice_waits_until_the_day_after_heavy_rain() -> None:
    sunday = date(2026, 11, 8)
    week = [
        DailyForecast(date=sunday + timedelta(days=i), condition=condition, rain_mm=0)
        for i, condition in enumerate(["rain", "cloudy", "rain", "heavy_rain", "sunny"])
    ]

    assert build_advice(week, "very_wet") == (
        "no siembres ni abones hasta el jueves. Tu suelo ya está muy húmedo."
    )


def _open_meteo_payload(today: date) -> dict:
    days = [(today + timedelta(days=i)).isoformat() for i in range(7)]
    return {
        "timezone": "America/Lima",
        "daily_units": {},
        "daily": {
            "time": days,
            "temperature_2m_max": [31.2, 30, 29, 28, 30, 32, 33],
            "precipitation_sum": [12.0, 0, 8, 40, 2, 0, 0],
            "precipitation_probability_max": [70, 10, 60, 90, 30, 0, 0],
            "weather_code": [63, 3, 61, 95, 3, 0, 1],
        },
    }


def _power_daily_payload(today: date) -> dict:
    dates = [(today - timedelta(days=i)).strftime("%Y%m%d") for i in range(1, 46)]
    return {
        "properties": {
            "parameter": {
                "PRECTOTCORR": dict.fromkeys(dates, 3.0),
                "T2M": dict.fromkeys(dates, 27.0),
                "GWETTOP": dict.fromkeys(dates, 0.85),
            }
        },
        "parameters": {},
    }


def _power_climatology_payload() -> dict:
    def monthly(value: float) -> dict:
        return {**dict.fromkeys(MONTHS, value), "ANN": value}

    return {
        "properties": {
            "parameter": {
                "PRECTOTCORR": monthly(1.0),
                "T2M": monthly(25.0),
                "GWETTOP": monthly(0.45),
            }
        },
        "parameters": {},
    }


def test_climate_overview_endpoint(client) -> None:
    today = date.today()
    with respx.mock(assert_all_called=True) as mock:
        mock.get(OPEN_METEO_URL).mock(
            return_value=httpx.Response(200, json=_open_meteo_payload(today))
        )
        mock.get(POWER_DAILY_URL).mock(
            return_value=httpx.Response(200, json=_power_daily_payload(today))
        )
        mock.get(POWER_CLIMATOLOGY_URL).mock(
            return_value=httpx.Response(200, json=_power_climatology_payload())
        )
        r = client.get("/api/v1/app/climate-overview", params={"lat": -5.19, "lon": -80.63})

    assert r.status_code == 200
    data = r.json()
    assert data["today"] == {
        "date": today.isoformat(),
        "condition": "moderate_rain",
        "rain_probability": 0.7,
        "rain_mm": 12.0,
        "temperature_c": 31.0,
    }
    assert [d["condition"] for d in data["week"]][3] == "heavy_rain"
    assert data["advice"].endswith("Tu suelo ya está muy húmedo.")

    by_metric = {a["metric"]: a for a in data["anomalies"]}
    assert by_metric["rainfall"]["comparison"] == {"type": "times_normal", "factor": 3.0}
    assert by_metric["temperature"]["comparison"] == {
        "type": "degrees_from_normal",
        "delta": 2.0,
    }
    assert by_metric["soil_moisture"]["comparison"] == {
        "type": "moisture_category",
        "level": "very_wet",
    }


def test_climate_overview_survives_power_outage(client) -> None:
    today = date.today()
    with respx.mock(assert_all_called=False) as mock:
        mock.get(OPEN_METEO_URL).mock(
            return_value=httpx.Response(200, json=_open_meteo_payload(today))
        )
        mock.get(POWER_DAILY_URL).mock(return_value=httpx.Response(400, text="bad"))
        mock.get(POWER_CLIMATOLOGY_URL).mock(
            return_value=httpx.Response(200, json=_power_climatology_payload())
        )
        r = client.get("/api/v1/app/climate-overview", params={"lat": -5.19, "lon": -80.63})

    assert r.status_code == 200
    assert r.json()["anomalies"] == []
