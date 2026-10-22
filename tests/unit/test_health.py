from __future__ import annotations


def test_health_ok(client) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_openapi_served(client) -> None:
    r = client.get("/openapi.json")
    assert r.status_code == 200
    data = r.json()
    assert data["info"]["title"] == "spaceapps-2026-core"
    paths = data["paths"]
    assert "/health" in paths
    assert "/health/sources" in paths
    assert "/api/v1/climate/history" in paths
    assert "/api/v1/climate/forecast" in paths
    assert "/api/v1/precipitation" in paths
    assert "/api/v1/vegetation/jobs" in paths
    assert "/api/v1/soil-moisture/jobs" in paths
    assert "/api/v1/jobs/{job_id}" in paths
    assert "/api/v1/projections" in paths
    assert "/api/v1/features" in paths


def test_error_envelope_consistent(client) -> None:
    r = client.get("/api/v1/jobs/does-not-exist")
    assert r.status_code == 404
    body = r.json()
    assert "error" in body
    assert body["error"]["code"] == "http_error"
    assert "message" in body["error"]


def test_validation_error_envelope(client) -> None:
    r = client.get("/api/v1/climate/history", params={"lat": 999, "lon": 0})
    assert r.status_code == 422
    body = r.json()
    assert body["error"]["code"] == "validation_error"
    assert "details" in body["error"]
