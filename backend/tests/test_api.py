from fastapi.testclient import TestClient

from backend.main import app


def test_public_api_surface_is_registered():
    with TestClient(app) as client:
        assert client.get("/").status_code == 200
        assert client.get("/api/system/status").status_code == 200
        assert client.get("/api/stats").status_code == 200
        assert client.get("/api/cameras").status_code == 200
        derived = client.get("/api/attendance/derived")
        assert derived.status_code == 200
        assert derived.json()["status"] == "success"


def test_openapi_contains_core_routes():
    with TestClient(app) as client:
        paths = client.get("/openapi.json").json()["paths"]
    assert "/api/attendance/derived" in paths
    assert "/api/enrollments" in paths
    assert "/api/detections/stream" in paths
