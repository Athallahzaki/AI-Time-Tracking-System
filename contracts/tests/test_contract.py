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
        "identity.resolved",
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


# --------------------------------------------------------------------------
# ReID dan jadwal analisis (dok 12 §3.3, §3.6)
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def reid() -> list:
    return _read("reid-tertunda.events.ndjson")


@pytest.fixture(scope="module")
def jadwal() -> list:
    return _read("jadwal-mati.events.ndjson")


def test_event_lama_tidak_mendapat_field_wajib_baru():
    """Aturan evolusi: skema lama tetap valid. Menambah field WAJIB ke event
    yang sudah ada memutus engine/backend yang belum diperbarui. Daftar di
    `required_baseline.json` adalah keadaan sebelum ReID/jadwal; satu-satunya
    tipe yang boleh tidak ada di sana adalah `identity.resolved`."""
    baseline = json.loads((Path(__file__).parent / "required_baseline.json").read_text(encoding="utf-8"))
    from contracts.validator.schema_validator import _SCHEMA, _TYPE_TO_DEF

    for mtype, required in baseline.items():
        sekarang = set(_SCHEMA["$defs"][_TYPE_TO_DEF[mtype]].get("required", []))
        assert sekarang <= set(required), f"{mtype} mendapat field wajib baru: {sorted(sekarang - set(required))}"
    assert set(_TYPE_TO_DEF) - set(baseline) == {"identity.resolved"}


def test_nilai_lama_enum_tetap_sah(validator, berbalik_lama):
    hb = next(m for m in berbalik_lama if m["type"] == "track.heartbeat")
    for source in ("face", "tracking"):
        assert validator.validate_message(dict(hb, identity_source=source)) == []
    ended = dict(next(m for m in berbalik_lama if m["type"] == "track.ended"))
    for reason in ("left_frame", "occluded_timeout", "merged_into_other_track",
                   "camera_lost", "engine_shutdown", "identity_released"):
        assert validator.validate_message(dict(ended, reason=reason)) == []


@pytest.mark.parametrize("source", ["face", "tracking", "reid", "reid_retro"])
def test_identity_source_baru_sah_di_semua_tempat(validator, source):
    hb = {
        "type": "track.heartbeat", "v": 1, "ts": "2025-09-19T00:00:30.000Z", "seq": 1,
        "track_uuid": "tr_a", "person_id": "4471", "pts": 30.0,
        "at": "2025-09-19T00:00:30.000Z", "identity_source": source, "confidence": 0.8,
    }
    snapshot = {
        "type": "snapshot", "v": 1, "ts": "2025-09-19T00:00:30.000Z", "seq": 2,
        "pts_wallclock_offset": {"r1": {"stream_epoch": 0, "offset": 1758240000.0}},
        "live": [{"track_uuid": "tr_a", "camera_id": "r1", "stream_epoch": 0,
                  "person_id": "4471", "identity_source": source, "since_pts": 1.0}],
    }
    frame = {
        "type": "view.frame", "v": 1, "ts": "2025-09-19T00:00:30.000Z",
        "camera_id": "r1", "stream_epoch": 0, "pts": 30.0, "at": "2025-09-19T00:00:30.000Z",
        "boxes": [{"track_uuid": "tr_a", "bbox": [0.1, 0.1, 0.2, 0.5], "identity_source": source}],
    }
    for message in (hb, snapshot, frame):
        assert validator.validate_message(message) == [], message["type"]


@pytest.mark.parametrize("bad", ["Reid", "ReID", "reid-retro", "body", ""])
def test_identity_source_asing_ditolak(validator, bad):
    hb = {
        "type": "track.heartbeat", "v": 1, "ts": "2025-09-19T00:00:30.000Z", "seq": 1,
        "track_uuid": "tr_a", "person_id": None, "pts": 30.0,
        "at": "2025-09-19T00:00:30.000Z", "identity_source": bad, "confidence": 0.8,
    }
    assert validator.validate_message(hb)


def test_schedule_off_sah_di_track_ended_dan_interval(validator, berbalik_lama):
    ended = dict(next(m for m in berbalik_lama if m["type"] == "track.ended"), reason="schedule_off")
    interval = dict(next(m for m in berbalik_lama if m["type"] == "presence.interval"),
                    end_reason="schedule_off", end_source="forced")
    assert validator.validate_message(ended) == []
    assert validator.validate_message(interval) == []


def test_end_reason_sejenis_schedule_off_ditolak(validator, berbalik_lama):
    ended = dict(next(m for m in berbalik_lama if m["type"] == "track.ended"), reason="schedule-off")
    assert validator.validate_message(ended)


def test_identity_resolved_fixture_bersih(reid):
    errors, _ = run(reid)
    assert errors == [], "\n".join(str(e) for e in errors)


def _resolved(reid):
    return next(m for m in reid if m["type"] == "identity.resolved")


@pytest.mark.parametrize("field", ["anon_id", "person_id", "at", "reason", "track_uuids", "moved_intervals"])
def test_identity_resolved_field_wajib(validator, reid, field):
    message = dict(_resolved(reid))
    del message[field]
    assert validator.validate_message(message)


def test_identity_resolved_ke_person_anon_ditolak(validator, reid):
    """Menyelesaikan ANON ke ANON lain bukan penyelesaian."""
    assert validator.validate_message(dict(_resolved(reid), person_id="ANON-0002"))


def test_identity_resolved_anon_id_salah_bentuk_ditolak(validator, reid):
    for bad in ("4471", "anon-0001", "ANON-", "ANON 1"):
        assert validator.validate_message(dict(_resolved(reid), anon_id=bad)), bad


def test_identity_resolved_track_uuids_kosong_ditolak(validator, reid):
    assert validator.validate_message(dict(_resolved(reid), track_uuids=[]))


def test_identity_resolved_alasan_di_luar_enum_ditolak(validator, reid):
    assert validator.validate_message(dict(_resolved(reid), reason="reid_match"))


def test_identity_resolved_moved_intervals_bukan_interval_id_ditolak(validator, reid):
    assert validator.validate_message(dict(_resolved(reid), moved_intervals=["tr_r1-t1"]))


def test_identity_resolved_kosong_moved_intervals_sah(validator, reid):
    assert validator.validate_message(dict(_resolved(reid), moved_intervals=[])) == []


def test_identity_resolved_lewat_kanal_events(validator, reid):
    assert validator.channel_of("identity.resolved") == "events"
    assert validator.validate_message(_resolved(reid), expected_channel="view")


def test_interval_dipindah_yang_bukan_milik_anon_ditolak(reid):
    messages = copy.deepcopy(reid)
    anon = next(m for m in messages if m["type"] == "presence.interval" and m["person_id"] == "ANON-0001")
    anon["person_id"] = "4471"  # sudah berlabel karyawan sebelum resolusi, tapi masih didaftarkan
    errors, _ = run(messages)
    assert any("bukan `ANON-0001`" in e.detail for e in errors)


def test_interval_dipindah_yang_belum_dipancarkan_ditolak(reid):
    """Interval sesudah resolusi sudah berlabel karyawan; mendaftarkannya di
    moved_intervals berarti merujuk sesuatu yang belum ada."""
    messages = copy.deepcopy(reid)
    nyata = next(m for m in messages if m["type"] == "presence.interval" and m["person_id"] == "4471")
    _resolved(messages)["moved_intervals"].append(nyata["interval_id"])
    errors, _ = run(messages)
    assert any("belum pernah dipancarkan" in e.detail for e in errors)


def test_interval_anon_terlewat_dari_daftar_ditolak(reid):
    messages = copy.deepcopy(reid)
    _resolved(messages)["moved_intervals"] = []
    errors, _ = run(messages)
    assert any("kehadiran tak bertuan" in e.detail for e in errors)


def test_interval_dipindah_yang_tak_pernah_ada_ditolak(reid):
    messages = copy.deepcopy(reid)
    _resolved(messages)["moved_intervals"].append("iv_hantu-0001")
    errors, _ = run(messages)
    assert any("belum pernah dipancarkan" in e.detail for e in errors)


def test_anon_dipakai_lagi_sesudah_resolved_ditolak(reid):
    messages = copy.deepcopy(reid)
    nyata = next(m for m in messages if m["type"] == "presence.interval" and m["person_id"] == "4471")
    nyata["person_id"] = "ANON-0001"
    errors, _ = run(messages)
    assert any("dipakai lagi sesudah" in e.detail for e in errors)


def test_resolved_dua_kali_ditolak(reid):
    messages = copy.deepcopy(reid)
    dup = copy.deepcopy(_resolved(messages))
    dup["seq"] = messages[-1]["seq"] + 1
    messages.append(dup)
    errors, _ = run(messages)
    assert any("dua kali" in e.detail for e in errors)


def test_resolved_dengan_track_tak_dikenal_ditolak(reid):
    messages = copy.deepcopy(reid)
    _resolved(messages)["track_uuids"].append("tr_hantu")
    errors, _ = run(messages)
    assert any("track_uuids" in e.path for e in errors)


def test_anon_tak_pernah_diselesaikan_hanya_peringatan(reid):
    """Rekaman yang dipotong sebelum resolusi itu sah; di hari penuh itu
    sinyal untuk HR. Jadi peringatan, bukan error."""
    messages = [m for m in copy.deepcopy(reid) if m["type"] != "identity.resolved"]
    for i, m in enumerate(messages, start=1):
        m["seq"] = i
    errors, warnings = run(messages)
    assert errors == []
    assert any("tidak pernah `identity.resolved`" in w.detail for w in warnings)


def test_jadwal_mati_fixture_bersih(jadwal):
    errors, warnings = run(jadwal)
    assert errors == [], "\n".join(str(e) for e in errors)
    assert not any("kegagalan tracking" in w.detail for w in warnings)


def test_schedule_off_wajib_forced(jadwal):
    messages = copy.deepcopy(jadwal)
    interval = next(m for m in messages if m["type"] == "presence.interval" and m["end_reason"] == "schedule_off")
    interval["end_source"] = "face"
    errors, _ = run(messages)
    assert any("forced" in e.detail for e in errors)


def test_schedule_off_saat_kamera_putus_ditolak(jadwal):
    messages = copy.deepcopy(jadwal)
    idx = next(i for i, m in enumerate(messages) if m["type"] == "track.ended" and m["reason"] == "schedule_off")
    messages.insert(idx, {
        "type": "camera.failed", "v": 1, "ts": messages[idx]["ts"], "seq": 0,
        "camera_id": "r1", "reason": "connection_refused", "retry_in_seconds": 5,
    })
    for i, m in enumerate(messages, start=1):
        m["seq"] = i
    errors, _ = run(messages)
    assert any("schedule_off" in e.detail for e in errors)
