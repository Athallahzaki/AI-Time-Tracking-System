"""Pengaturan realtime engine (`set_tuning`) dan tampilan dashboard lewat API admin (overhaul 3 Nov)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.core import database
from backend.main import app
from backend.routers.auth import login_limiter
from backend.services import engine_connection_manager as ecm
from backend.services.auth_service import auth_service
from backend.services.engine_client import EngineConnectionError
from backend.services.engine_integration import engine_integration


class FakeClient:
    def __init__(self, connected=True):
        self.connected = connected
        self.sent = []

    def send(self, message):
        if not self.connected:
            raise EngineConnectionError("Engine socket is not connected")
        self.sent.append(message)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "backend.db")
    database.init_database()
    login_limiter.reset()
    fake = FakeClient()
    monkeypatch.setattr(ecm.engine_connection_manager, "client", fake)
    from backend.services import engine_client as client_module
    monkeypatch.setattr(client_module, "engine_client", fake)
    auth_service.create_user(username="admin", password="rahasia-panjang", role="admin")
    client = TestClient(app)
    token = client.post("/api/auth/login", json={"username": "admin", "password": "rahasia-panjang"}).json()
    headers = {"Authorization": f"Bearer {token['access_token']}"}
    return client, headers, fake


OVERRIDES = {"analysis_trigger": {"enabled": True}, "recognition": {"match_threshold": 0.42}}


def test_simpan_kirim_ke_engine_lalu_ack_diterima(env):
    client, headers, fake = env
    body = client.put("/api/settings/tuning", json={"overrides": OVERRIDES}, headers=headers).json()
    assert fake.sent[-1]["type"] == "set_tuning" and fake.sent[-1]["tuning"] == OVERRIDES
    assert body["status"]["state"] == "pending" and body["engine_connected"] is True

    engine_integration.handle_control({"type": "ack", "in_reply_to": "set_tuning", "accepted": True,
                                               "effective_tuning": {"analysis_trigger": {"enabled": True}}})
    body = client.get("/api/settings/tuning", headers=headers).json()
    assert body["status"]["state"] == "accepted" and body["overrides"] == OVERRIDES
    assert body["status"]["effective"]["analysis_trigger"]["enabled"] is True
    audit = client.get("/api/settings/audit", headers=headers).json()
    assert "Kalibrasi engine" in str(audit)


def test_ditolak_engine_override_kembali_ke_yang_terakhir_diterima(env):
    client, headers, fake = env
    client.put("/api/settings/tuning", json={"overrides": OVERRIDES}, headers=headers)
    engine_integration.handle_control({"type": "ack", "in_reply_to": "set_tuning", "accepted": True})
    client.put("/api/settings/tuning", json={"overrides": {"recognition": {"match_margin": -1}}}, headers=headers)
    engine_integration.handle_control({"type": "ack", "in_reply_to": "set_tuning", "accepted": False,
                                               "reason": "recognition.match_margin=-1 harus angka 0.0..1.0"})
    body = client.get("/api/settings/tuning", headers=headers).json()
    assert body["overrides"] == OVERRIDES, "dashboard tidak boleh menampilkan nilai yang tidak berlaku"
    assert body["status"]["state"] == "rejected" and "match_margin" in body["status"]["reason"]


def test_engine_offline_disimpan_dan_dikirim_saat_tersambung(env, monkeypatch):
    client, headers, fake = env
    fake.connected = False
    body = client.put("/api/settings/tuning", json={"overrides": OVERRIDES}, headers=headers).json()
    assert body["status"]["state"] == "offline"
    fake.connected = True
    monkeypatch.setattr(ecm, "set_cameras_message", lambda: {"type": "set_cameras", "cameras": []})
    ecm.engine_connection_manager.sync_desired_state()
    assert [m["type"] for m in fake.sent] == ["set_cameras", "set_roster", "set_tuning"]
    assert fake.sent[-1]["tuning"] == OVERRIDES


def test_hanya_admin_dan_bentuk_divalidasi(env):
    client, headers, _ = env
    anonim = TestClient(app)                      # tanpa cookie sesi dari login di fixture
    assert anonim.get("/api/settings/tuning").status_code in (401, 403)
    bad = client.put("/api/settings/tuning", json={"overrides": {"detector": 0.5}}, headers=headers)
    assert bad.status_code == 400


def test_tampilan_publik_dibaca_admin_menulis(env):
    client, headers, _ = env
    assert client.get("/api/settings/display").json() == {}
    value = {"webrtc": {"playoutDelaySeconds": 5.0}, "boxes": {"maxAgeMs": 1000}}
    anonim = TestClient(app)
    assert anonim.put("/api/settings/display", json=value).status_code in (401, 403)
    assert anonim.get("/api/settings/display").status_code == 200
    assert client.put("/api/settings/display", json=value, headers=headers).json() == value
    assert client.get("/api/settings/display").json() == value
