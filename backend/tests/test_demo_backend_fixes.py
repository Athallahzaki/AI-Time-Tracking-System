"""Bug backend yang ditemukan saat review 6 Okt, dikunci dengan tes.

1. Dekorator nyasar membuat POST /api/attendance/corrections dijawab oleh
   get_active_sessions: koreksi tidak pernah tersimpan, tetapi responsnya 200.
2. Kegagalan evaluasi pelanggaran menggagalkan ingest event yang sudah tersimpan.
3. PUT /api/settings/policy membuang semua komentar di policy.yaml.
4. Isi email pelanggaran: waktu berupa epoch mentah, tanpa tautan dashboard.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from backend.core import database
from backend.main import app
from backend.services import violation_service as violation_module
from backend.services.auth_service import auth_service
from backend.services.break_policy import break_policy
from backend.services.email_service import EmailService
from backend.services.event_ingestion import event_ingestion_service
from backend.services.policy_service import PolicyService

FIXTURE = Path("contracts/fixtures/happy-path.events.ndjson")


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "backend.db")
    database.init_database()
    return database


def _admin_token(client) -> str:
    auth_service.create_user(username="admin", password="rahasia-panjang", role="admin")
    response = client.post("/api/auth/login", json={"username": "admin", "password": "rahasia-panjang"})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


# -- 1. rute ganda -------------------------------------------------------------

def test_tidak_ada_rute_ganda():
    routes = Counter(
        (method, route.path)
        for route in app.routes if isinstance(route, APIRoute)
        for method in route.methods
    )
    duplicates = [key for key, count in routes.items() if count > 1]
    assert duplicates == []


def test_post_koreksi_benar_benar_menyimpan(db):
    client = TestClient(app)          # tanpa `with`: lifespan (koneksi engine) tidak jalan
    body = {"person_id": "4471", "date": "2026-10-06", "adjustment_minutes": -5,
            "corrected_by": "admin", "reason": "uji"}
    assert client.post("/api/attendance/corrections", json=body).status_code == 401

    token = _admin_token(client)
    response = client.post("/api/attendance/corrections", json=body,
                           headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, response.text
    assert response.json()["correction"]["person_id"] == "4471"
    saved = database.get_corrections()
    assert len(saved) == 1 and saved[0]["reason"] == "uji"


def test_tidak_ada_rute_koreksi_di_enrollment():
    paths = {route.path for route in app.routes if isinstance(route, APIRoute)}
    assert "/api/enrollments/corrections" not in paths


# -- 2. ingest tahan kegagalan evaluasi pelanggaran ------------------------------------

def _heartbeat():
    for line in FIXTURE.read_text(encoding="utf-8").splitlines():
        message = json.loads(line)
        if message.get("type") == "track.heartbeat":
            return message
    raise AssertionError("fixture tanpa heartbeat")


def test_evaluasi_pelanggaran_gagal_tidak_menggagalkan_ingest(db, monkeypatch):
    def boom(event):
        raise RuntimeError("DB notifikasi rusak")

    monkeypatch.setattr(violation_module.violation_service, "evaluate_event", boom)
    assert event_ingestion_service.ingest(_heartbeat(), outbox_id="ob-uji") is True
    assert event_ingestion_service.ingest(_heartbeat(), outbox_id="ob-uji") is False   # duplikat


# -- pelanggaran -> satu notifikasi per orang per hari --------------------------------

def test_pelanggaran_dan_notifikasi_sekali_per_hari(db, monkeypatch):
    usage = {"status": "exceeded", "used_seconds": 1900.0, "allowance_seconds": 1800.0,
             "remaining_seconds": 0.0}
    monkeypatch.setattr(violation_module.free_time_ledger, "usage", lambda **kw: dict(usage))
    service = violation_module.violation_service
    first = service.evaluate("4471", "2026-10-06", now=1_000.0)
    second = service.evaluate("4471", "2026-10-06", now=2_000.0)
    assert first["created"] is True and second["created"] is False
    assert len(database.get_violations(person_id="4471")) == 1
    assert len(database.get_notifications(person_id="4471")) == 1


# -- 3. policy.yaml tetap berkomentar ----------------------------------------------------

def test_ubah_policy_menyimpan_komentar(tmp_path):
    source = Path("backend/configs/policy.yaml").read_text(encoding="utf-8")
    path = tmp_path / "policy.yaml"
    path.write_text(source, encoding="utf-8")
    keep = {name: getattr(break_policy, name) for name in (
        "timezone_name", "qualification_seconds", "daily_allowance_minutes",
        "warning_remaining_minutes", "official_breaks", "visit_merge_gap_seconds",
        "open_presence_stale_seconds")}
    try:
        result = PolicyService(path).update_free_time(2.0, 1.0)
    finally:
        for name, value in keep.items():
            setattr(break_policy, name, value)
        break_policy.__post_init__()
    text = path.read_text(encoding="utf-8")
    assert result["daily_free_time_allowance_minutes"] == 2.0
    assert "daily_free_time_allowance_minutes: 2.0" in text
    assert "warning_remaining_minutes: 1.0" in text
    assert "# Kebijakan jatah free time" in text and "minta HRD" in text
    assert text.count("\n") == source.count("\n")


def test_policy_tanpa_kunci_ditambahkan(tmp_path):
    path = tmp_path / "policy.yaml"
    path.write_text("# catatan\ntimezone: Asia/Jakarta\n", encoding="utf-8")
    text = PolicyService(path)._render({"daily_free_time_allowance_minutes": 30.0,
                                        "warning_remaining_minutes": 5.0})
    assert text.startswith("# catatan\n")
    assert "daily_free_time_allowance_minutes: 30.0" in text


# -- 4. isi email -------------------------------------------------------------------------

def test_isi_email_terbaca(monkeypatch):
    from backend.core.config import settings

    monkeypatch.setattr(settings, "dashboard_url", "http://dashboard.local")
    subject, body = EmailService.compose_notification({
        "person_id": "4471", "type": "free_time_exceeded",
        "title": "Batas jatah waktu terlampaui",
        "event_at": 1_791_250_000.0,          # 2026-10-06 ±11:46 WIB
        "payload": {"date": "2026-10-06", "used_seconds": 1900.0, "allowance_seconds": 1800.0},
    })
    assert "4471" in subject
    assert "Tanggal: 2026-10-06" in body
    assert "06-10-2026" in body and "1791250000" not in body
    assert "Pemakaian: 31.7 dari 30.0 menit" in body
    assert "Jenis: free_time_exceeded" in body
    assert "http://dashboard.local" in body
