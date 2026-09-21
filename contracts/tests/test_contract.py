"""Tes untuk validator kontrak.

Yang diuji bukan "apakah pesan benar lolos" — itu bagian yang mudah dan tidak
pernah gagal. Yang diuji adalah **apakah pesan salah benar-benar ditolak**,
karena validator yang meloloskan segalanya persis sama tidak bergunanya dengan
tidak punya validator sama sekali, cuma dengan tambahan rasa aman palsu.

Setiap kasus negatif di sini adalah bug nyata yang bisa terjadi, bukan karangan:
lihat komentarnya masing-masing.

    pytest contracts/tests -q
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from contracts.validator import ConformanceChecker, SchemaValidator

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


@pytest.fixture(scope="module")
def validator() -> SchemaValidator:
    return SchemaValidator()


def _read(name: str) -> list:
    lines = (FIXTURES / name).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


@pytest.fixture(scope="module")
def berbalik_lama() -> list:
    """Fixture yang dihasilkan `fake_engine`, bukan tulisan tangan.

    Itu disengaja: validator dan engine palsu saling memeriksa. Kalau salah
    satunya bergeser, yang lain yang menangkapnya -- dan itu jauh lebih
    berguna daripada dua berkas yang ditulis orang yang sama dengan asumsi
    yang sama.
    """
    return _read("berbalik-lama.events.ndjson")


@pytest.fixture(scope="module")
def stitching() -> list:
    return _read("stitching.events.ndjson")


def run(messages, allow_replay=False):
    validator = SchemaValidator()
    issues = []
    for index, message in enumerate(messages, start=1):
        message = dict(message)
        message["_line"] = index
        issues.extend(validator.validate_message(message, line=index, expected_channel="events"))
    report = ConformanceChecker(allow_replay=allow_replay).check(
        [dict(m, _line=i) for i, m in enumerate(messages, start=1)]
    )
    return issues + report.errors, report.warnings


# --------------------------------------------------------------------------
# dasar
# --------------------------------------------------------------------------


def test_fixture_bersih(berbalik_lama):
    errors, _ = run(berbalik_lama)
    assert errors == [], "\n".join(str(e) for e in errors)


def test_semua_tipe_di_dokumen_ada_di_skema(validator):
    wajib = {
        "hello", "hello_ack", "ack", "replay_gap", "set_cameras", "set_roster",
        "enroll", "enroll_result", "presence.interval", "track.started",
        "track.identified", "track.heartbeat", "track.resumed",
        "track.identity_changed", "track.ended", "person.unidentified_present",
        "camera.online", "camera.failed", "camera.degraded", "camera.coverage",
        "engine.health", "snapshot", "enrollment_needed", "view.frame",
    }
    assert wajib <= set(validator.known_types)


def test_field_tak_dikenal_diabaikan(validator, berbalik_lama):
    """Aturan evolusi: penambahan field tidak memutus penerima lama."""
    message = dict(berbalik_lama[1])
    message["field_yang_belum_ada_di_v1"] = {"apa pun": [1, 2, 3]}
    assert validator.validate_message(message) == []


# --------------------------------------------------------------------------
# hal-hal yang skema harus tolak
# --------------------------------------------------------------------------


def test_end_source_track_lost_ditolak(validator, berbalik_lama):
    """Nilai ini muncul di contoh ARCHITECTURE dan ENGINE_PROTOCOL, dan salah.

    `track_lost` adalah end_reason, bukan end_source. Kalau backend menulis tes
    dari contoh itu, ketidakcocokannya baru ketahuan di M3.
    """
    interval = dict(next(m for m in berbalik_lama if m["type"] == "presence.interval"))
    interval["end_source"] = "track_lost"
    issues = validator.validate_message(interval)
    assert any("end_source" in issue.path for issue in issues)


def test_pts_berbentuk_unix_epoch_ditolak(validator, berbalik_lama):
    """Contoh di ARCHITECTURE §4.2 memakai 1726712531.20 sebagai start_pts.

    pts relatif terhadap awal stream. Angka sebesar itu berarti seseorang
    mengira pts adalah jam dinding — dan seluruh aritmetika interval jadi salah
    diam-diam. Skema tidak bisa melarang angka besar, tapi conformance bisa
    menangkapnya lewat ketiadaan offset; yang bisa dilarang skema adalah pts
    negatif. Tes ini menjaga batas bawahnya.
    """
    started = dict(next(m for m in berbalik_lama if m["type"] == "track.started"))
    started["pts"] = -1.0
    assert validator.validate_message(started)


def test_bbox_piksel_ditolak(validator):
    frame = {
        "type": "view.frame", "v": 1, "ts": "2026-09-19T03:21:40.330Z",
        "camera_id": "r1", "stream_epoch": 0, "pts": 4900.33,
        "at": "2026-09-19T03:21:40.330Z",
        "boxes": [{"track_uuid": "tr_a", "bbox": [310, 220, 440, 780]}],
    }
    issues = validator.validate_message(frame)
    assert issues, "bbox piksel lolos — overlay akan meleset di substream"


def test_seq_di_kanal_view_ditolak(validator):
    """Kanal view best-effort dan tidak punya seq.

    Kalau seq muncul di sana, seseorang memasukkan view ke outbox, dan retensi
    outbox akan didominasi bbox per frame.
    """
    frame = {
        "type": "view.frame", "v": 1, "ts": "2026-09-19T03:21:40.330Z", "seq": 5,
        "camera_id": "r1", "stream_epoch": 0, "pts": 4900.33,
        "at": "2026-09-19T03:21:40.330Z", "boxes": [],
    }
    assert validator.validate_message(frame)


def test_track_identified_tanpa_track_started_pts_ditolak(validator, berbalik_lama):
    message = dict(next(m for m in berbalik_lama if m["type"] == "track.identified"))
    del message["track_started_pts"]
    assert validator.validate_message(message)


def test_track_ended_tanpa_exit_zone_ditolak(validator, berbalik_lama):
    message = dict(next(m for m in berbalik_lama if m["type"] == "track.ended"))
    del message["exit_zone"]
    assert validator.validate_message(message)


def test_interval_id_berbentuk_track_uuid_ditolak(validator, berbalik_lama):
    """Di contoh ENGINE_PROTOCOL, interval_id dan track_uuid nilainya identik.

    Satu track bisa menghasilkan lebih dari satu interval (identity_changed di
    tengah track), jadi id-nya akan bentrok.
    """
    interval = dict(next(m for m in berbalik_lama if m["type"] == "presence.interval"))
    interval["interval_id"] = interval["track_uuid"]
    assert validator.validate_message(interval)


def test_timestamp_tanpa_Z_ditolak(validator, berbalik_lama):
    """Offset non-Z membuat perbandingan string antar timestamp jadi salah."""
    message = dict(berbalik_lama[1])
    message["at"] = "2026-09-19T10:15:00+07:00"
    assert validator.validate_message(message)


# --------------------------------------------------------------------------
# hal-hal yang hanya conformance bisa tangkap
# --------------------------------------------------------------------------


def test_lubang_seq_tanpa_replay_gap_ditolak(berbalik_lama):
    messages = copy.deepcopy(berbalik_lama)
    for message in messages[3:]:
        message["seq"] += 10
    errors, _ = run(messages)
    assert any("lubang di seq" in error.detail for error in errors)


def test_kamera_putus_tidak_boleh_berarti_pulang(berbalik_lama):
    """Bug yang baru ketahuan saat penggajian: satu ruangan penuh orang
    ditandai pulang pada detik yang sama karena kamera mati."""
    messages = copy.deepcopy(berbalik_lama)
    first_end = next(i for i, m in enumerate(messages) if m["type"] == "track.ended")

    messages.insert(first_end, {
        "type": "camera.failed", "v": 1, "ts": messages[first_end]["ts"], "seq": 0,
        "camera_id": "r1", "reason": "connection_refused", "retry_in_seconds": 5,
    })
    messages[first_end + 1]["reason"] = "left_frame"
    messages[first_end + 1]["exit_zone"] = "door"
    for index, message in enumerate(messages, start=1):
        message["seq"] = index

    errors, _ = run(messages)
    assert any("camera_lost" in error.detail for error in errors)


def test_reconnect_tanpa_menaikkan_stream_epoch_ditolak(berbalik_lama):
    """§6.6: offset wajib ditetapkan ulang tiap reconnect. Tanpa stream_epoch,
    backend tidak punya cara tahu offset mana yang berlaku untuk pesan mana."""
    messages = copy.deepcopy(berbalik_lama)
    online_again = dict(messages[0])
    online_again["seq"] = len(messages) + 1
    online_again["pts_wallclock_offset"] = 1758250000.0
    messages.append(online_again)

    errors, _ = run(messages)
    assert any("stream_epoch" in error.path for error in errors)


def test_track_started_pts_yang_dikarang_ditolak(berbalik_lama):
    messages = copy.deepcopy(berbalik_lama)
    identified = next(m for m in messages if m["type"] == "track.identified")
    identified["track_started_pts"] = identified["pts"]  # "mulai saat wajah terbaca"
    errors, _ = run(messages)
    assert any("track_started_pts" in error.path for error in errors)


def test_akumulasi_harian_ditolak(berbalik_lama):
    """Engine mengamati, backend memutuskan. Kalau angka ini lolos sekali, ia
    akan dipakai backend, dan garis §2.1 sudah bocor tanpa ada yang sadar."""
    messages = copy.deepcopy(berbalik_lama)
    interval = next(m for m in messages if m["type"] == "presence.interval")
    interval["daily_total_seconds"] = 22800
    errors, _ = run(messages)
    assert any("kebijakan" in error.detail for error in errors)


def test_interval_menunjuk_pendahulu_yang_tidak_ada_ditolak(berbalik_lama):
    messages = copy.deepcopy(berbalik_lama)
    intervals = [m for m in messages if m["type"] == "presence.interval"]
    intervals[-1]["prev_interval_id"] = "iv_tidak-pernah-ada"
    errors, _ = run(messages)
    assert any("prev_interval_id" in error.path for error in errors)


def test_snapshot_tanpa_offset_kamera_hidup_ditolak(berbalik_lama):
    messages = copy.deepcopy(berbalik_lama)
    snapshot = next(m for m in messages if m["type"] == "snapshot")
    snapshot["pts_wallclock_offset"] = {}
    errors, _ = run(messages)
    assert any("pts_wallclock_offset" in error.path for error in errors)


def test_penyambungan_lintas_kamera_ditolak(stitching):
    """Lintas ruangan itu handoff — penyambungan sesi milik backend, bukan
    bukti perseptual milik engine."""
    messages = copy.deepcopy(stitching)
    resumed = next(m for m in messages if m["type"] == "track.resumed")
    for message in messages:
        if message["type"] == "track.started" and message["track_uuid"] == resumed["track_uuid"]:
            message["camera_id"] = "r2"
    errors, _ = run(messages)
    assert any("handoff" in error.detail for error in errors)


def test_celah_interior_berlabel_left_frame_diperingatkan(berbalik_lama):
    messages = copy.deepcopy(berbalik_lama)
    interval = next(m for m in messages if m["type"] == "presence.interval")
    interval["end_reason"] = "left_frame"
    _, warnings = run(messages)
    assert any("kegagalan tracking" in warning.detail for warning in warnings)
