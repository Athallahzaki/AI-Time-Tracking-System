"""Paket F: panel debug Fase 1 (kesehatan, log, rekaman CSV)."""
from __future__ import annotations

import csv
import io
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core import database
from backend.routers import debug
from backend.services.auth_service import auth_service

app = FastAPI()
app.include_router(debug.router)
client = TestClient(app)


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "backend.db")
    database._initialized_for = None
    database.init_database()
    debug._LOGS.clear()
    yield
    database._initialized_for = None


def _token(username: str, role: str) -> dict:
    employee = database.create_employee(f"E-{username}", username)["id"] if role == "viewer" else None
    auth_service.create_user(username=username, password="rahasia-uji-123", role=role,
                             employee_internal_id=employee)
    return {"Authorization": f"Bearer {auth_service.login(username, 'rahasia-uji-123')['access_token']}"}


def _health(seq: int, ts: float, fps: float, stale: int, tolak: int, state: str = "online") -> None:
    database.save_protocol_event(ts, "engine.health", {
        "type": "engine.health", "v": 1, "seq": seq, "models_loaded": True, "queue_depth": 0,
        "drop_rate": 0.0, "cameras": {"cam01": state},
        "camera_metrics": {"cam01": {"effective_fps": fps, "lag_seconds": 0.4, "frames_dropped_stale": stale}},
        "identity_metrics": {"reid_tolak_galeri_travel_time": tolak},
    }, seq, "ob-1")


def test_mati_secara_default_dan_tidak_terdaftar(monkeypatch):
    monkeypatch.delenv("DEBUG_PANEL_ENABLED", raising=False)
    assert debug.debug_panel_enabled() is False
    from backend.main import app as real_app
    assert not any(getattr(route, "path", "").startswith("/api/debug") for route in real_app.routes)
    monkeypatch.setenv("DEBUG_PANEL_ENABLED", "1")
    assert debug.debug_panel_enabled() is True


def test_kesehatan_menampilkan_laju_dan_alasan_gagal_terakhir():
    admin = _token("bos", "admin")
    import time
    now = time.time()
    _health(1, now - 60, fps=10.0, stale=100, tolak=4)
    _health(2, now - 30, fps=9.5, stale=160, tolak=7)        # 30 dtk kemudian
    database.save_protocol_event(now - 20, "camera.failed", {
        "type": "camera.failed", "camera_id": "cam01",
        "reason": "404 dari rtsp://netbird-client:8554/cam01b", "retry_in_seconds": 60}, 3, "ob-1")

    body = client.get("/api/debug/health", headers=admin).json()
    camera = body["cameras"][0]
    assert (camera["camera_id"], camera["state"]) == ("cam01", "online")
    assert camera["per_minute"]["frames_dropped_stale"] == 120.0     # 60 dalam 30 dtk
    assert body["identity_per_minute"]["reid_tolak_galeri_travel_time"] == 6.0
    assert camera["last_event"]["type"] == "camera.failed" and "404" in camera["last_event"]["reason"]
    assert 25 <= body["health_age_seconds"] <= 40 and body["window_seconds"] == 30.0


def test_kesehatan_kosong_tanpa_laporan_engine():
    body = client.get("/api/debug/health", headers=_token("bos", "admin")).json()
    assert body["health_age_seconds"] is None and body["cameras"] == []


def test_rekaman_csv_sesuai_rentang_dan_format_lag_probe():
    admin = _token("bos", "admin")
    for i, ts in enumerate((1000.0, 1030.0, 1060.0, 1090.0), start=1):
        _health(i, ts, fps=10.0 - i, stale=i, tolak=0)
    response = client.get("/api/debug/health.csv", params={"from": 1030, "to": 1060}, headers=admin)
    assert response.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert [(r["elapsed_s"], r["source"], r["camera_id"], r["fps"], r["dropped"]) for r in rows] == [
        ("0.0", "health", "cam01", "8.0", "2"), ("30.0", "health", "cam01", "7.0", "3")]


def test_log_backend_dan_frontend_satu_daftar():
    admin, viewer = _token("bos", "admin"), _token("andi", "viewer")
    handler = debug._RingHandler(level=logging.INFO)
    log = logging.getLogger("uji.debug")
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    try:
        log.info("biasa")
        log.warning("engine terputus: %s", "timeout")
    finally:
        log.removeHandler(handler)
    sent = client.post("/api/debug/client-log", headers=viewer, json={
        "message": "[WebRTC] WHEP signaling failed: HTTP 404", "url": "/dashboard"})
    assert sent.status_code == 204

    everything = client.get("/api/debug/logs", headers=admin).json()["logs"]
    assert [(e["source"], e["level"]) for e in everything] == [
        ("frontend", "ERROR"), ("backend", "WARNING"), ("backend", "INFO")]       # terbaru dulu
    assert everything[0]["logger"] == "andi" and "engine terputus: timeout" == everything[1]["message"]
    warnings = client.get("/api/debug/logs", headers=admin, params={"min_level": "WARNING"}).json()["logs"]
    assert len(warnings) == 2
    assert len(client.get("/api/debug/logs", headers=admin, params={"source": "frontend"}).json()["logs"]) == 1


def test_hanya_admin_yang_membaca_dan_pesan_browser_dibatasi():
    viewer = _token("andi", "viewer")
    for path in ("/api/debug/health", "/api/debug/logs", "/api/debug/health.csv?from=0&to=1"):
        assert client.get(path, headers=viewer).status_code == 403, path
        assert client.get(path).status_code == 401, path
    assert client.post("/api/debug/client-log", json={"message": "x"}).status_code == 401
    assert client.post("/api/debug/client-log", headers=viewer,
                       json={"message": "x" * 2001}).status_code == 422
