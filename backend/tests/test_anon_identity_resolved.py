"""ANON-xxxx tidak pernah dihitung/dinotifikasi; identity.resolved memindahkan waktunya ke karyawan.

Kontrak: contracts/schema/engine_protocol.schema.json ($defs.anon_id, $defs.identity_resolved).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.core import database
from backend.schemas.employee import EmployeeCreateRequest, EmployeeUpdateRequest
from backend.services import event_ingestion as ingestion_module
from backend.services.event_ingestion import EventIngestionService
from backend.services.free_time import free_time_ledger
from backend.services.notification_service import notification_service
from backend.services.violation_service import violation_service

JKT = ZoneInfo("Asia/Jakarta")
FIXTURE = Path(__file__).resolve().parents[2] / "contracts" / "fixtures" / "reid-tertunda.events.ndjson"
OUTBOX = "ob-anon"


def jkt(day, hh, mm, ss=0, month=9):
    return datetime(2026, month, day, hh, mm, ss, tzinfo=JKT)


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "backend.db")
    monkeypatch.setattr(database, "_initialized_for", None, raising=False)
    database.init_database()
    free_time_ledger.tracker.clear()
    free_time_ledger.invalidate()
    yield database
    free_time_ledger.tracker.clear()
    free_time_ledger.invalidate()


@pytest.fixture
def surat(monkeypatch):
    """Rekam notifikasi pelanggaran yang dibuat (dan email yang akan dikirim)."""
    dibuat = []
    asli = notification_service.create_violation_notification

    def rekam(violation):
        hasil = asli(violation)
        dibuat.append((violation["person_id"], violation["date"], hasil))
        return hasil

    monkeypatch.setattr(notification_service, "create_violation_notification", rekam)
    email = []
    monkeypatch.setattr(
        "backend.services.notification_service.email_service.enqueue_notification",
        lambda notification: email.append(notification) or False,
    )
    return {"notifikasi": dibuat, "email": email}


@pytest.fixture
def dirty(monkeypatch):
    tanggal = []
    asli = ingestion_module.mark_report_dirty
    monkeypatch.setattr(
        ingestion_module, "mark_report_dirty",
        lambda tgl: tanggal.append(tgl) or asli(tgl),
    )
    return tanggal


class Aliran:
    """Pengirim event ke EventIngestionService dengan seq berurutan."""

    def __init__(self, outbox=OUTBOX):
        self.outbox, self.seq, self.service = outbox, 0, EventIngestionService()

    def kirim(self, event, seq=None):
        if seq is None:
            self.seq += 1
            seq = self.seq
        event = {"v": 1, "ts": event.get("at") or event.get("end_at"), "seq": seq, **event}
        return self.service.ingest(event, outbox_id=self.outbox)

    def interval(self, interval_id, person_id, camera, mulai, selesai, track="tr_x"):
        return self.kirim({
            "type": "presence.interval", "interval_id": interval_id, "person_id": person_id,
            "camera_id": camera, "stream_epoch": 0, "track_uuid": track,
            "start_pts": 0.0, "end_pts": (selesai - mulai).total_seconds(),
            "start_at": iso(mulai), "end_at": iso(selesai),
            "start_source": "tracking", "end_source": "tracking",
            "start_zone": "interior", "end_zone": "interior", "end_reason": "left_frame",
            "identity_confidence": 0.7, "evidence_count": 2,
            "ts": iso(selesai),
        })

    def resolved(self, anon, person, saat, track_uuids, moved, seq=None):
        return self.kirim({
            "type": "identity.resolved", "anon_id": anon, "person_id": person,
            "at": iso(saat), "reason": "face_confirmed",
            "track_uuids": track_uuids, "moved_intervals": moved,
        }, seq=seq)


def buat_karyawan(employee_id="4471"):
    return database.create_employee(employee_id=employee_id, name=f"Karyawan {employee_id}")


def hitung(tabel):
    with database.connect() as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {tabel}").fetchone()[0]


# ---------------------------------------------------------------------------
# fixture kontrak
# ---------------------------------------------------------------------------

def test_fixture_reid_tertunda_ujung_ke_ujung(db, surat):
    buat_karyawan("4471")
    service = EventIngestionService()
    baris = [json.loads(x) for x in FIXTURE.read_text(encoding="utf-8").splitlines() if x.strip()]
    sebelum = [e for e in baris if e["seq"] < 16]
    sesudah = [e for e in baris if e["seq"] >= 16]
    akhir = datetime.fromisoformat("2025-09-19T00:10:00+00:00").timestamp()

    for event in sebelum:
        service.ingest(event, outbox_id=OUTBOX)
    assert database.get_violations() == []
    assert surat["notifikasi"] == [] and surat["email"] == []
    assert free_time_ledger.usage("ANON-0001", "2025-09-19", now=akhir)["used_seconds"] == 0.0
    assert database.get_presence_intervals(0, akhir, "4471") == []

    for event in sesudah:
        service.ingest(event, outbox_id=OUTBOX)
    milik = database.get_presence_intervals(0, akhir * 2, "4471")
    assert {i["interval_id"] for i in milik} == {"iv_r1-0001", "iv_r2-0001"}
    dipindah = next(i for i in milik if i["interval_id"] == "iv_r1-0001")
    assert dipindah["identity_source"] == "reid_retro"
    assert dipindah["original_person_id"] == "ANON-0001"
    assert database.get_presence_intervals(0, akhir * 2, "ANON-0001") == []

    pemakaian = free_time_ledger.usage("4471", "2025-09-19", now=akhir)
    # 60 s (r1) + 220 s (r2), jarak 10 s <= merge gap -> satu kunjungan, 20 s pertama gratis.
    assert len(pemakaian["visits"]) == 1
    assert pemakaian["visits"][0]["countable_seconds"] == pytest.approx(60 + 10 + 220)
    assert pemakaian["used_seconds"] == pytest.approx(60 + 10 + 220 - 20)
    assert database.get_violations() == [] and surat["notifikasi"] == []


# ---------------------------------------------------------------------------
# ANON tidak dihitung
# ---------------------------------------------------------------------------

def test_anon_lebih_30_menit_tidak_ada_pelanggaran(db, surat):
    buat_karyawan("4471")
    aliran = Aliran()
    aliran.interval("iv_a1", "ANON-7f3a", "r1", jkt(22, 9, 0), jkt(22, 9, 45), track="tr_a")
    sekarang = jkt(22, 10, 0).timestamp()

    pemakaian = free_time_ledger.usage("ANON-7f3a", "2026-09-22", now=sekarang)
    assert pemakaian["used_seconds"] == 0.0 and pemakaian["status"] != "exceeded"
    assert database.get_violations() == []
    assert surat["notifikasi"] == [] and surat["email"] == []
    assert hitung("notifications") == 0
    assert "ANON-7f3a" not in free_time_ledger.known_person_ids()


def test_evaluasi_langsung_mengabaikan_anon(db, surat):
    aliran = Aliran()
    aliran.interval("iv_a1", "ANON-1", "r1", jkt(22, 9, 0), jkt(22, 9, 45), track="tr_a")
    sekarang = jkt(22, 10, 0).timestamp()
    assert violation_service.evaluate("ANON-1", "2026-09-22", now=sekarang) is None
    assert violation_service.evaluate_event({
        "type": "track.heartbeat", "person_id": "ANON-1", "at": iso(jkt(22, 10, 0)),
    }) == []
    assert violation_service.evaluate_event({
        "type": "snapshot", "ts": iso(jkt(22, 10, 0)),
        "live": [{"person_id": "ANON-1"}, {"person_id": "ANON-2"}],
    }) == []
    assert database.get_violations() == []


def test_track_anon_terbuka_tidak_dihitung(db):
    aliran = Aliran()
    aliran.kirim({"type": "track.started", "track_uuid": "tr_a", "camera_id": "r1",
                  "stream_epoch": 0, "pts": 0.0, "at": iso(jkt(22, 9, 0)), "zone": "door"})
    aliran.kirim({"type": "track.heartbeat", "track_uuid": "tr_a", "person_id": "ANON-1",
                  "pts": 3000.0, "at": iso(jkt(22, 9, 50)), "identity_source": "reid",
                  "confidence": 0.6})
    now = jkt(22, 9, 50).timestamp()
    assert free_time_ledger.tracker.open_segments(now, 90.0) == []
    assert "ANON-1" not in free_time_ledger.tracker.open_person_ids()
    assert free_time_ledger.usage("ANON-1", "2026-09-22", now=now)["used_seconds"] == 0.0


# ---------------------------------------------------------------------------
# identity.resolved
# ---------------------------------------------------------------------------

def test_resolved_melebihi_jatah_satu_pelanggaran_satu_notifikasi(db, surat):
    buat_karyawan("4471")
    aliran = Aliran()
    aliran.interval("iv_a1", "ANON-7f3a", "r1", jkt(22, 9, 0), jkt(22, 9, 45), track="tr_a")
    assert database.get_violations() == []

    aliran.resolved("ANON-7f3a", "4471", jkt(22, 9, 46), ["tr_a"], ["iv_a1"])

    pelanggaran = database.get_violations()
    assert [(p["person_id"], p["date"]) for p in pelanggaran] == [("4471", "2026-09-22")]
    assert [(n[0], n[1]) for n in surat["notifikasi"]] == [("4471", "2026-09-22")]
    assert hitung("notifications") == 1
    assert all(p["person_id"] != "ANON-7f3a" for p in pelanggaran)


def test_resolved_lintas_kamera(db):
    buat_karyawan("4471")
    aliran = Aliran()
    aliran.interval("iv_a1", "ANON-9", "r1", jkt(22, 9, 0), jkt(22, 9, 10), track="tr_a")
    aliran.interval("iv_a2", "ANON-9", "r2", jkt(22, 9, 10, 10), jkt(22, 9, 20), track="tr_b")
    aliran.resolved("ANON-9", "4471", jkt(22, 9, 21), ["tr_a", "tr_b"], ["iv_a1", "iv_a2"])

    milik = database.get_presence_intervals(0, jkt(23, 0, 0).timestamp(), "4471")
    assert {i["interval_id"] for i in milik} == {"iv_a1", "iv_a2"}
    assert {i["camera_id"] for i in milik} == {"r1", "r2"}
    assert all(i["identity_source"] == "reid_retro" for i in milik)
    pemakaian = free_time_ledger.usage("4471", "2026-09-22", now=jkt(22, 10, 0).timestamp())
    assert len(pemakaian["visits"]) == 1
    assert pemakaian["used_seconds"] == pytest.approx(20 * 60 - 20)


def test_resolved_lintas_tengah_malam(db, surat, dirty):
    buat_karyawan("4471")
    aliran = Aliran()
    aliran.interval("iv_m1", "ANON-5", "r1", jkt(22, 23, 40), jkt(23, 0, 20), track="tr_a")
    aliran.interval("iv_m2", "ANON-5", "r2", jkt(23, 0, 25), jkt(23, 0, 50), track="tr_b")
    assert database.get_violations() == []
    dirty.clear()

    aliran.resolved("ANON-5", "4471", jkt(23, 0, 55), ["tr_a", "tr_b"], ["iv_m1", "iv_m2"])

    assert {"2026-09-22", "2026-09-23"} <= set(dirty)
    sekarang = jkt(23, 1, 0).timestamp()
    malam1 = free_time_ledger.usage("4471", "2026-09-22", now=sekarang)
    malam2 = free_time_ledger.usage("4471", "2026-09-23", now=sekarang)
    assert malam1["used_seconds"] == pytest.approx(20 * 60 - 20)
    assert malam2["used_seconds"] == pytest.approx(20 * 60 + 25 * 60 - 20)  # tiap kunjungan punya 20 dtk gratis; kunjungan 1 sudah memakainya kemarin
    pelanggaran = [(p["person_id"], p["date"]) for p in database.get_violations()]
    assert pelanggaran == [("4471", "2026-09-23")]
    assert len(surat["notifikasi"]) == 1


def test_resolved_ke_person_tidak_ada_di_master(db, surat, dirty):
    aliran = Aliran()
    aliran.interval("iv_a1", "ANON-3", "r1", jkt(22, 9, 0), jkt(22, 9, 45), track="tr_a")
    dirty.clear()

    aliran.resolved("ANON-3", "9999", jkt(22, 9, 46), ["tr_a"], ["iv_a1"])

    review = database.get_hr_reviews()
    assert len(review) == 1
    assert review[0]["review_reason"] == "missing_employee"
    assert review[0]["original_person_id"] == "ANON-3"
    assert database.get_presence_intervals(0, jkt(23, 0, 0).timestamp(), "9999") == []
    assert database.get_violations() == []
    assert surat["notifikasi"] == []
    assert dirty == ["2026-09-22"]  # hanya penandaan dasar event; atribusi gagal tidak menandai ulang


def test_replay_resolved_tidak_dobel(db, surat):
    buat_karyawan("4471")
    aliran = Aliran()
    aliran.interval("iv_a1", "ANON-7f3a", "r1", jkt(22, 9, 0), jkt(22, 9, 45), track="tr_a")
    assert aliran.resolved("ANON-7f3a", "4471", jkt(22, 9, 46), ["tr_a"], ["iv_a1"]) is True
    pemakaian = free_time_ledger.usage("4471", "2026-09-22", now=jkt(22, 10, 0).timestamp())

    assert aliran.resolved("ANON-7f3a", "4471", jkt(22, 9, 46), ["tr_a"], ["iv_a1"], seq=aliran.seq) is False

    assert hitung("identity_attributions") == 1
    assert len(database.get_violations()) == 1
    assert len(surat["notifikasi"]) == 1
    ulang = free_time_ledger.usage("4471", "2026-09-22", now=jkt(22, 10, 0).timestamp())
    assert ulang["used_seconds"] == pytest.approx(pemakaian["used_seconds"])


def test_heartbeat_setelah_resolved_dihitung_sejak_awal_track(db):
    buat_karyawan("4471")
    aliran = Aliran()
    aliran.kirim({"type": "track.started", "track_uuid": "tr_a", "camera_id": "r1",
                  "stream_epoch": 0, "pts": 0.0, "at": iso(jkt(22, 9, 0)), "zone": "door"})
    aliran.kirim({"type": "track.heartbeat", "track_uuid": "tr_a", "person_id": "ANON-1",
                  "pts": 300.0, "at": iso(jkt(22, 9, 5)), "identity_source": "reid", "confidence": 0.6})
    aliran.resolved("ANON-1", "4471", jkt(22, 9, 6), ["tr_a"], [])
    aliran.kirim({"type": "track.heartbeat", "track_uuid": "tr_a", "person_id": "4471",
                  "pts": 420.0, "at": iso(jkt(22, 9, 7)), "identity_source": "face", "confidence": 0.8})

    now = jkt(22, 9, 7).timestamp()
    segmen = free_time_ledger.tracker.open_segments(now, 90.0, "4471")
    assert [(s["start_ts"], s["segment_id"]) for s in segmen] == [(jkt(22, 9, 0).timestamp(), "tr_a")]
    assert free_time_ledger.usage("4471", "2026-09-22", now=now)["used_seconds"] == pytest.approx(7 * 60 - 20)


def test_track_terbuka_dialihkan_saat_resolved_tanpa_menunggu_heartbeat(db):
    buat_karyawan("4471")
    aliran = Aliran()
    aliran.kirim({"type": "track.started", "track_uuid": "tr_a", "camera_id": "r1",
                  "stream_epoch": 0, "pts": 0.0, "at": iso(jkt(22, 9, 0)), "zone": "door"})
    aliran.kirim({"type": "track.heartbeat", "track_uuid": "tr_a", "person_id": "ANON-1",
                  "pts": 300.0, "at": iso(jkt(22, 9, 5)), "identity_source": "reid", "confidence": 0.6})
    aliran.resolved("ANON-1", "4471", jkt(22, 9, 6), ["tr_a"], [])

    segmen = free_time_ledger.tracker.open_segments(jkt(22, 9, 6).timestamp(), 90.0, "4471")
    assert len(segmen) == 1 and segmen[0]["start_ts"] == jkt(22, 9, 0).timestamp()


def test_tidak_dobel_dengan_interval_anon_yang_dipindah(db):
    """Interval ANON sudah ditutup (identity_released); sisa track terbuka mulai dari akhir interval."""
    buat_karyawan("4471")
    aliran = Aliran()
    aliran.kirim({"type": "track.started", "track_uuid": "tr_a", "camera_id": "r1",
                  "stream_epoch": 0, "pts": 0.0, "at": iso(jkt(22, 9, 0)), "zone": "door"})
    aliran.kirim({"type": "track.heartbeat", "track_uuid": "tr_a", "person_id": "ANON-1",
                  "pts": 300.0, "at": iso(jkt(22, 9, 5)), "identity_source": "reid", "confidence": 0.6})
    aliran.interval("iv_a1", "ANON-1", "r1", jkt(22, 9, 0), jkt(22, 9, 5), track="tr_a")
    aliran.resolved("ANON-1", "4471", jkt(22, 9, 5, 30), ["tr_a"], ["iv_a1"])
    aliran.kirim({"type": "track.heartbeat", "track_uuid": "tr_a", "person_id": "4471",
                  "pts": 420.0, "at": iso(jkt(22, 9, 7)), "identity_source": "face", "confidence": 0.8})

    pemakaian = free_time_ledger.usage("4471", "2026-09-22", now=jkt(22, 9, 7).timestamp())
    # 09:00-09:07 sekali saja (5 menit interval dipindah + 2 menit sisa track), bukan 12 menit.
    assert pemakaian["visits"][0]["countable_seconds"] == pytest.approx(7 * 60)
    assert pemakaian["used_seconds"] == pytest.approx(7 * 60 - 20)


# ---------------------------------------------------------------------------
# awalan ANON- dicadangkan
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("model", [EmployeeCreateRequest, EmployeeUpdateRequest])
def test_skema_employee_menolak_awalan_anon(model):
    data = {"name": "X"} if model is EmployeeCreateRequest else {}
    with pytest.raises(ValidationError):
        model(employee_id="ANON-1", **data)
    assert model(employee_id="anon-1", **data).employee_id == "anon-1"
    assert model(employee_id="4471", **data).employee_id == "4471"


def test_update_tanpa_employee_id_tetap_lolos():
    assert EmployeeUpdateRequest(name="Baru").employee_id is None


def test_api_employee_anon_ditolak_422(tmp_path):
    from backend.tests.test_employee_crud import _create_admin_token, client, fresh_db  # noqa: F401
    database.DB_PATH = type(database.DB_PATH)(str(tmp_path / "api.db"))
    database._initialized_for = None
    database.init_database()
    headers = {"Authorization": f"Bearer {_create_admin_token()}"}

    buat = client.post("/api/employees", json={"employee_id": "ANON-1", "name": "Palsu"}, headers=headers)
    assert buat.status_code == 422

    ok = client.post("/api/employees", json={"employee_id": "E1", "name": "Asli"}, headers=headers)
    assert ok.status_code in (200, 201)
    internal_id = ok.json().get("id") or ok.json().get("employee", {}).get("id")
    ubah = client.patch(f"/api/employees/{internal_id}", json={"employee_id": "ANON-2"}, headers=headers)
    assert ubah.status_code == 422
