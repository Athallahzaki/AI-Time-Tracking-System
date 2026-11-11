"""Uji penerimaan Jatah & Pelanggaran: JAT-02, JAT-05, JAT-07, JAT-12, JAT-14.

Tiap tes menyebut test case klien yang dijaganya. Tanpa engine: event durabel
ditulis langsung ke database sementara.
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from backend.core import database
from backend.core.config import settings
from backend.services import violation_service as violation_module
from backend.services.break_policy import BreakPolicy
from backend.services.email_service import EmailService
from backend.services.free_time import FreeTimeLedger

JKT = ZoneInfo("Asia/Jakarta")
DAY = "2026-09-22"
_seq = {"n": 0}


def at(hh, mm, ss=0):
    return datetime(2026, 9, 22, hh, mm, ss, tzinfo=JKT)


def interval(person, cam, start, end):
    _seq["n"] += 1
    iso = lambda dt: dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")  # noqa: E731
    event = {
        "v": 1, "ts": iso(end), "type": "presence.interval", "interval_id": f"iv_{_seq['n']}",
        "person_id": person, "camera_id": cam, "stream_epoch": 0,
        "start_at": iso(start), "end_at": iso(end), "start_zone": "interior",
        "end_zone": "interior", "end_reason": "left_frame", "identity_confidence": 0.9,
        "evidence_count": 2,
    }
    database.save_protocol_event(end.timestamp(), event["type"], event, _seq["n"], "ob-1")


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "backend.db")
    database.init_database()
    return database


@pytest.fixture
def lobby(monkeypatch):
    """Kamera `lobby` dikonfigurasi tidak memotong jatah; `r1` tetap ruang rekreasi."""
    from backend.core.config import CameraConfig
    cameras = dict(settings.cameras)
    cameras["lobby"] = CameraConfig(id="lobby", code="LOBBY", name="Lobby",
                                    source_uri="rtsp://x/lobby", counts_free_time=False)
    monkeypatch.setattr(settings, "_cameras_cache", cameras)


def usage(person, hh=12, mm=0, **policy):
    return FreeTimeLedger(BreakPolicy(official_breaks={}, **policy)).usage(
        person, DAY, now=at(hh, mm).timestamp())


# ---- JAT-02 ---------------------------------------------------------------

def test_jat02_lobby_tercatat_tetapi_tidak_memotong_jatah(db, lobby):
    interval("E1", "lobby", at(9, 0), at(9, 5))
    result = usage("E1")
    assert result["used_seconds"] == 0.0
    assert len(result["visits"]) == 1                       # terdeteksi dan tercatat
    assert result["visits"][0]["counts_free_time"] is False
    assert result["visits"][0]["charged_seconds"] == 0.0


def test_jat02_lobby_tidak_memperpanjang_kunjungan_rekreasi(db, lobby):
    interval("E1", "r1", at(9, 0), at(9, 5))        # 300 s, 20 s pertama gratis -> 280
    interval("E1", "lobby", at(9, 5, 10), at(9, 10))  # langsung ke lobby: tidak ditagih
    result = usage("E1")
    assert result["used_seconds"] == pytest.approx(280.0)
    assert [v["counts_free_time"] for v in result["visits"]] == [True, False]


def test_jat02_default_semua_kamera_dihitung(db):
    """Tanpa `counts_free_time` di cameras.yaml, perilaku lama: semua kamera ditagih."""
    interval("E1", "kamera-tak-dikenal", at(9, 0), at(9, 5))
    assert usage("E1")["used_seconds"] == pytest.approx(280.0)


# ---- JAT-12 ---------------------------------------------------------------

def test_jat12_jatah_berbeda_per_karyawan(db):
    database.create_employee("E1", "Satu", allowance_minutes=30)
    database.create_employee("E2", "Dua", allowance_minutes=60)
    for person in ("E1", "E2"):
        interval(person, "r1", at(9, 0), at(9, 35, 20))     # 35 menit ditagih
    first, second = usage("E1"), usage("E2")
    assert (first["allowance_seconds"], first["status"]) == (1800.0, "exceeded")
    assert (second["allowance_seconds"], second["status"]) == (3600.0, "ok")
    assert second["remaining_seconds"] == pytest.approx(1500.0)


def test_jat12_tanpa_jatah_pribadi_memakai_jatah_global(db):
    database.create_employee("E1", "Satu")
    assert usage("E1", daily_allowance_minutes=45)["allowance_seconds"] == 2700.0
    database.update_employee(database.get_employee_by_employee_id("E1")["id"], allowance_minutes=10)
    assert usage("E1", daily_allowance_minutes=45)["allowance_seconds"] == 600.0
    database.update_employee(database.get_employee_by_employee_id("E1")["id"], allowance_minutes=None)
    assert usage("E1", daily_allowance_minutes=45)["allowance_seconds"] == 2700.0


def test_jat12_jatah_kecil_tidak_langsung_berstatus_peringatan(db):
    """Jatah 4 menit di bawah ambang peringatan global 5 menit: ambangnya separuh jatah."""
    database.create_employee("E1", "Satu", allowance_minutes=4)
    interval("E1", "r1", at(9, 0), at(9, 1, 20))             # 60 s ditagih, sisa 180
    assert usage("E1")["status"] == "ok"
    interval("E1", "r1", at(10, 0), at(10, 1, 30))           # +70 s -> sisa 110 <= 120
    assert usage("E1")["status"] == "warning"


# ---- JAT-07 ---------------------------------------------------------------

def test_jat07_pengecualian_tidak_berlaku_mundur_dan_bisa_dicabut(db):
    interval("E1", "r1", at(9, 0), at(9, 5))                 # sebelum pengecualian: 280 s
    database.add_exemption("E1", "r1", created_by="hr", reason="tugas",
                           effective_from=at(9, 30).timestamp())
    interval("E1", "r1", at(10, 0), at(10, 10))              # dikecualikan
    interval("E2", "r1", at(10, 0), at(10, 10))              # orang lain: tetap ditagih
    interval("E1", "r2", at(10, 30), at(10, 35))             # lokasi lain: tetap ditagih
    result = usage("E1")
    assert result["used_seconds"] == pytest.approx(560.0)    # 280 + 280, tanpa 10 menit itu
    assert [v["counts_free_time"] for v in result["visits"]] == [True, False, True]
    assert usage("E2")["used_seconds"] == pytest.approx(580.0)

    exemption_id = database.get_exemptions("E1")[0]["id"]
    assert database.revoke_exemption(exemption_id, "hr", at=at(11, 0).timestamp())
    interval("E1", "r1", at(11, 30), at(11, 35))             # setelah dicabut: ditagih lagi
    result = usage("E1")
    assert result["used_seconds"] == pytest.approx(840.0)
    assert result["visits"][1]["counts_free_time"] is False  # kunjungan lama tetap dikecualikan
    assert database.revoke_exemption(exemption_id, "hr") is False


# ---- JAT-05 dan JAT-14 ----------------------------------------------------

@pytest.fixture
def service(db, monkeypatch):
    ledger = FreeTimeLedger(BreakPolicy(official_breaks={}))  # 30 menit, peringatan sisa 5
    monkeypatch.setattr(violation_module, "free_time_ledger", ledger)
    sent = []
    monkeypatch.setattr(violation_module.notification_service, "publish", lambda n: None)
    from backend.services import notification_service as notification_module
    monkeypatch.setattr(notification_module.email_service, "enqueue_notification", sent.append)
    return violation_module.ViolationService(), sent


def test_jat05_peringatan_dini_tercatat_sekali(service):
    svc, sent = service
    database.create_employee("E1", "Anugrah")
    interval("E1", "r1", at(9, 0), at(9, 26, 20))            # 26 menit: sisa 4 <= 5
    for minute in (30, 31, 32):                              # dievaluasi berulang kali
        assert svc.evaluate("E1", DAY, now=at(9, minute).timestamp()) is None
    notes = database.get_notifications(person_id="E1")
    assert [n["type"] for n in notes] == ["free_time_warning"]
    assert "Anugrah (E1)" in notes[0]["message"]
    assert sent == []                                        # peringatan dini tidak di-email


def test_jat05_jat14_melewati_batas_satu_pelanggaran_satu_email(service):
    svc, sent = service
    database.create_employee("E1", "Anugrah")
    interval("E1", "r1", at(9, 0), at(9, 26, 20))
    svc.evaluate("E1", DAY, now=at(9, 30).timestamp())
    interval("E1", "r1", at(10, 0), at(10, 10))              # total 36 menit > 30
    for minute in (15, 16):
        svc.evaluate("E1", DAY, now=at(10, minute).timestamp())
    types = sorted(n["type"] for n in database.get_notifications(person_id="E1"))
    assert types == ["free_time_exceeded", "free_time_warning"]
    assert len(sent) == 1 and sent[0]["type"] == "free_time_exceeded"

    subject, body = EmailService.compose_notification(sent[0])
    assert "Anugrah (E1)" in subject and "Karyawan: Anugrah (E1)" in body
    assert "dari 30.0 menit" in body
