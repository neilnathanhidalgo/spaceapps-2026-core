from __future__ import annotations

import httpx
import respx


def _power_payload() -> dict:
    return {
        "type": "Feature",
        "properties": {
            "parameter": {
                "T2M": {"20240101": 25.0, "20240102": 25.5},
                "PRECTOTCORR": {"20240101": 0.0, "20240102": 3.1},
            }
        },
        "header": {"title": "POWER"},
        "parameters": {"T2M": {"units": "C"}, "PRECTOTCORR": {"units": "mm/day"}},
    }


def test_features_json(client) -> None:
    with respx.mock(assert_all_called=True) as mock:
        mock.get("https://power.larc.nasa.gov/api/temporal/daily/point").mock(
            return_value=httpx.Response(200, json=_power_payload())
        )

        r = client.get(
            "/api/v1/features",
            params={
                "lat": -5.19,
                "lon": -80.63,
                "start": "2024-01-01",
                "end": "2024-01-02",
                "variables": ["t2m_mean", "precipitation"],
            },
        )
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 2
    assert {"date", "t2m_mean", "precipitation"} <= set(rows[0].keys())
    assert rows[0]["t2m_mean"] == 25.0


def test_features_csv(client) -> None:
    with respx.mock(assert_all_called=True) as mock:
        mock.get("https://power.larc.nasa.gov/api/temporal/daily/point").mock(
            return_value=httpx.Response(200, json=_power_payload())
        )

        r = client.get(
            "/api/v1/features",
            params={
                "lat": -5.19,
                "lon": -80.63,
                "start": "2024-01-01",
                "end": "2024-01-02",
                "variables": ["t2m_mean"],
                "format": "csv",
            },
        )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    text = r.text
    assert "date" in text and "t2m_mean" in text
