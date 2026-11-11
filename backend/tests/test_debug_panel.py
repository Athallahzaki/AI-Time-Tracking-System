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


# ---- Paket H: Fase 2 (kontrak debug, sesi debug, crop) -----------------------

class _FakeEngine:
    """Engine ber-`debug.enabled`: menjawab lewat penangan debug backend, seperti koneksi sungguhan."""

    connected = True

    def __init__(self, supported: bool = True) -> None:
        self.sent = []
        self.supported = supported

    def send(self, message):
        self.sent.append(message)
        kind, rid = message["type"], message.get("request_id")
        base = {"v": 1, "ts": "2026-11-11T12:00:00.000Z"}
        if not self.supported:
            reply = {"type": "ack", **base, "in_reply_to": kind, "accepted": False, "reason": "tidak dikenal"}
        elif kind == "debug.subscribe":
            reply = {"type": "ack", **base, "in_reply_to": kind, "accepted": True}
        elif kind == "debug.crop_list":
            reply = {"type": "debug.crops", **base, "request_id": rid, "crops": [
                {"track_uuid": "tr_ab_7", "camera_id": "cam01", "at": 100.0, "person_id": "ANON-k3",
                 "identity_source": "reid"}]}
        else:
            found = message["track_uuid"] == "tr_ab_7"
            reply = {"type": "debug.crop", **base, "request_id": rid, "track_uuid": message["track_uuid"],
                     "found": found, **({"camera_id": "cam01", "at": 100.0, "width": 60, "height": 200,
                                         "jpeg_b64": "QUJD"} if found else {})}
        debug.engine_debug.handle(reply)


@pytest.fixture
def engine(monkeypatch):
    fake = _FakeEngine()
    monkeypatch.setattr(debug, "engine_client", fake)
    debug.engine_debug.subscribe(fake)
    debug._failures.clear()
    yield fake
    debug.engine_debug.engine_supported = None


def _debug_admin(username: str = "bos", can_debug: bool = True) -> dict:
    headers = _token(username, "admin")
    user_id = client.get("/api/debug/session", headers=headers) and auth_service.authenticate(
        headers["Authorization"].split(" ", 1)[1])["id"]
    database.update_user(user_id, can_debug=can_debug)
    return headers


def _audit() -> list:
    return [(row["actor"], row["setting"], row["new_value"]) for row in database.get_settings_audit(50)]


def test_mode_debug_butuh_izin_per_orang_dan_password_sendiri(engine):
    tanpa_izin = _debug_admin("admin-biasa", can_debug=False)
    assert client.post("/api/debug/session", headers=tanpa_izin,
                       json={"password": "rahasia-uji-123"}).status_code == 403
    berizin = _debug_admin("bos")
    assert client.get("/api/debug/crops", headers=berizin).status_code == 403          # belum dibuka
    assert client.post("/api/debug/session", headers=berizin, json={"password": "salah"}).status_code == 400
    opened = client.post("/api/debug/session", headers=berizin, json={"password": "rahasia-uji-123"})
    assert opened.status_code == 200
    status = client.get("/api/debug/session", headers=berizin).json()
    assert status["can_debug"] is True and status["engine_supported"] is True
    assert 29 * 60 < status["active_until"] - __import__("time").time() <= 30 * 60

    # Sesi debug melekat pada sesi login ITU: login lain milik orang yang sama tidak ikut terbuka.
    login_lain = {"Authorization": f"Bearer {auth_service.login('bos', 'rahasia-uji-123')['access_token']}"}
    assert client.get("/api/debug/crops", headers=login_lain).status_code == 403
    assert ("bos", "debug.session", '"password salah"') in _audit()
    assert ("bos", "debug.session", '"dibuka"') in _audit()


def test_password_salah_berulang_dikunci(engine):
    headers = _debug_admin()
    for _ in range(5):
        assert client.post("/api/debug/session", headers=headers, json={"password": "x"}).status_code == 400
    assert client.post("/api/debug/session", headers=headers,
                       json={"password": "rahasia-uji-123"}).status_code == 429      # benar pun ditolak


def test_mode_debug_mati_sendiri_dan_bisa_ditutup(engine):
    import time
    from backend.services.debug_service import DEBUG_SESSION_SECONDS, DebugSessions
    sessions = DebugSessions()
    until = sessions.open("sesi-a", now=1000.0)
    assert until == 1000.0 + DEBUG_SESSION_SECONDS == 1000.0 + 30 * 60
    assert sessions.expires_at("sesi-a", now=until - 1) == until
    assert sessions.expires_at("sesi-a", now=until + 1) is None                        # mati sendiri

    headers = _debug_admin()
    client.post("/api/debug/session", headers=headers, json={"password": "rahasia-uji-123"})
    assert client.get("/api/debug/crops", headers=headers).status_code == 200
    for key in list(debug.debug_sessions._expires):                                    # 30 menit berlalu
        debug.debug_sessions._expires[key] = time.time() - 1
    assert client.get("/api/debug/crops", headers=headers).status_code == 403
    client.post("/api/debug/session", headers=headers, json={"password": "rahasia-uji-123"})
    assert client.delete("/api/debug/session", headers=headers).status_code == 204
    assert client.get("/api/debug/crops", headers=headers).status_code == 403


def test_crop_butuh_alasan_dicatat_dan_tidak_di_cache(engine):
    headers = _debug_admin()
    client.post("/api/debug/session", headers=headers, json={"password": "rahasia-uji-123"})
    listed = client.get("/api/debug/crops", headers=headers).json()["crops"]
    assert listed[0]["person_id"] == "ANON-k3" and "jpeg_b64" not in listed[0]

    assert client.post("/api/debug/crop", headers=headers,
                       json={"track_uuid": "tr_ab_7", "reason": "x"}).status_code == 422       # alasan wajib
    assert client.post("/api/debug/crop", headers=headers,
                       json={"track_uuid": "../etc", "reason": "cek ANON"}).status_code == 422
    seen = client.post("/api/debug/crop", headers=headers,
                       json={"track_uuid": "tr_ab_7", "reason": "ANON baru tiap pindah ruangan"})
    assert seen.status_code == 200 and seen.headers["cache-control"] == "no-store"
    assert seen.json()["found"] is True and seen.json()["jpeg_b64"] == "QUJD"
    assert client.post("/api/debug/crop", headers=headers,
                       json={"track_uuid": "tr_lain", "reason": "cek ANON"}).json()["found"] is False
    crops_audited = [new for actor, setting, new in _audit() if setting == "debug.crop" and actor == "bos"]
    assert len(crops_audited) == 2 and "ANON baru tiap pindah ruangan" in "".join(crops_audited)
    assert not any("QUJD" in str(row) for row in _audit())                              # gambar tidak ikut tercatat


def test_engine_lama_atau_debug_mati_dilaporkan_bukan_menggantung(monkeypatch):
    fake = _FakeEngine(supported=False)
    monkeypatch.setattr(debug, "engine_client", fake)
    debug.engine_debug.subscribe(fake)
    try:
        headers = _debug_admin()
        client.post("/api/debug/session", headers=headers, json={"password": "rahasia-uji-123"})
        status = client.get("/api/debug/session", headers=headers).json()
        assert status["engine_supported"] is False and status["engine_reason"] == "tidak dikenal"
        refused = client.get("/api/debug/crops", headers=headers)
        assert refused.status_code == 503 and "tidak dikenal" in refused.json()["detail"]
    finally:
        debug.engine_debug.engine_supported = None


def test_log_engine_masuk_ke_daftar_yang_sama():
    admin = _token("bos", "admin")
    assert debug.engine_debug.handle({"type": "debug.log", "v": 1, "ts": "x", "channel": "view",
                                      "level": "WARNING", "logger": "engine.runtime.camera",
                                      "message": "[cam01] masih gagal dibuka: 404"}) is True
    assert debug.engine_debug.handle({"type": "view.frame"}) is False                   # bukan urusan debug
    entries = client.get("/api/debug/logs", headers=admin, params={"source": "engine"}).json()["logs"]
    assert [(e["level"], e["logger"]) for e in entries] == [("WARNING", "engine.runtime.camera")]


def test_izin_debug_diatur_admin_dan_tercatat():
    admin = _token("bos", "admin")
    other = _token("andi-admin", "admin")
    other_id = auth_service.authenticate(other["Authorization"].split(" ", 1)[1])["id"]
    from backend.routers import auth as auth_router
    app.include_router(auth_router.router) if not any(
        getattr(r, "path", "") == "/api/auth/users/{user_id}" for r in app.routes) else None
    patched = client.patch(f"/api/auth/users/{other_id}", headers=admin, json={"can_debug": True})
    assert patched.status_code == 200 and patched.json()["user"]["can_debug"] is True
    assert ("bos", "users.andi-admin.can_debug", "true") in _audit()
