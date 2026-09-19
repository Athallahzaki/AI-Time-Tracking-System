"""Tes `fake_engine`.

Tes paling penting di berkas ini bukan yang memeriksa satu skenario, tapi dua
yang memeriksa keseluruhannya:

- `test_setiap_skenario_lolos_kontrak` menjalankan keempat belas skenario lewat
  validator yang sama dengan yang akan dipakai untuk engine sungguhan. Engine
  palsu yang memancarkan sesuatu yang engine asli tidak boleh memancarkan
  adalah engine palsu yang mengajari backend hal yang salah.

- `test_fixture_yang_dicommit_masih_cocok` menangkap drift. Aturannya "fixture
  di-commit, bukan dihasilkan ulang" -- tes yang membandingkan dengan keluaran
  yang dihasilkan saat itu juga tidak menguji apa-apa. Jadi berkasnya
  di-commit, dan tes ini gagal kalau kode penurunan berubah tanpa ada yang
  merekam ulang dengan sengaja. Kegagalannya BUKAN gangguan: ia pertanyaan
  "kamu memang bermaksud mengubah arti fixture untuk tiga jalur sekaligus?"
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from contracts.validator import ConformanceChecker, SchemaValidator
from engine.tools.fake_engine import (
    Emitter, Outbox, ScenarioError, build_expected, from_mapping, load,
)

ROOT = Path(__file__).resolve().parent.parent.parent
SCENARIO_DIR = ROOT / "engine" / "tools" / "fake_engine" / "scenarios"
FIXTURE_DIR = ROOT / "contracts" / "fixtures"

SCENARIOS = sorted(SCENARIO_DIR.glob("*.yaml"))


def emit(path: Path):
    scenario = load(path)
    messages = Emitter(scenario, seed=42, view_fps=scenario.view_fps).run()
    return scenario, messages


def check(messages, channel):
    validator = SchemaValidator()
    payloads = [p for c, p in messages if c == channel]
    issues = []
    for index, payload in enumerate(payloads, start=1):
        issues.extend(validator.validate_message(payload, line=index, expected_channel=channel))
    report = ConformanceChecker().check(
        [dict(p, _line=i) for i, p in enumerate(payloads, start=1)]
    )
    return issues + report.errors


# --------------------------------------------------------------------------


def test_keempat_belas_skenario_wajib_ada():
    """ENGINE_PROTOCOL §6.3 mendaftar empat belas. Kurang satu berarti ada
    kegagalan integrasi yang tidak punya tempat untuk ketahuan."""
    wajib = {
        "happy-path", "berbalik-lama", "istirahat-asli", "kamera-mati",
        "identitas-tertukar", "reconnect-replay", "replay-gap",
        "orang-tak-dikenal", "dua-orang-mirip", "enrollment-ditolak",
        "roster-berubah", "stitching", "kamera-reconnect", "lintas-ruangan",
    }
    assert {load(path).name for path in SCENARIOS} == wajib


@pytest.mark.parametrize("path", SCENARIOS, ids=lambda p: p.stem)
def test_setiap_skenario_lolos_kontrak(path):
    _, messages = emit(path)
    errors = check(messages, "events")
    assert errors == [], "\n".join(str(e) for e in errors)


@pytest.mark.parametrize("path", SCENARIOS, ids=lambda p: p.stem)
def test_fixture_yang_dicommit_masih_cocok(path):
    scenario, messages = emit(path)
    for channel in ("events", "view"):
        payloads = [p for c, p in messages if c == channel]
        fixture = FIXTURE_DIR / f"{scenario.name}.{channel}.ndjson"
        if not payloads:
            assert not fixture.exists(), f"{fixture} ada tapi skenario tidak memancarkan {channel}"
            continue
        assert fixture.exists(), f"{fixture} hilang; jalankan --all --record"
        on_disk = [json.loads(line) for line in fixture.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert on_disk == payloads, (
            f"{fixture} tidak lagi cocok dengan keluaran emitter. Kalau perubahannya "
            "disengaja, rekam ulang dan sebutkan di commit apa yang berubah artinya "
            "untuk backend."
        )


@pytest.mark.parametrize("path", SCENARIOS, ids=lambda p: p.stem)
def test_deterministik(path):
    scenario = load(path)
    first = Emitter(scenario, seed=42, view_fps=scenario.view_fps).run()
    second = Emitter(scenario, seed=42, view_fps=scenario.view_fps).run()
    assert first == second


# --------------------------------------------------------------------------
# invarian per skenario
# --------------------------------------------------------------------------


def intervals_of(messages):
    return [p for c, p in messages if c == "events" and p["type"] == "presence.interval"]


def test_happy_path_interval_mulai_saat_track_lahir():
    """§4.4: dimundurkan ke kelahiran track, bukan ke saat wajah terbaca."""
    scenario, messages = emit(SCENARIO_DIR / "01-happy-path.yaml")
    started = next(p for c, p in messages if p["type"] == "track.started")
    identified = next(p for c, p in messages if p["type"] == "track.identified")
    interval = intervals_of(messages)[0]

    assert identified["pts"] > started["pts"], "skenario ini tidak menguji apa pun kalau keduanya sama"
    assert interval["start_pts"] == started["pts"]
    assert identified["track_started_pts"] == started["pts"]


def test_berbalik_lama_celahnya_berlabel_interior():
    scenario, messages = emit(SCENARIO_DIR / "02-berbalik-lama.yaml")
    expected = build_expected(scenario, messages)
    assert expected["counts"]["intervals"] == 2
    gap = expected["gaps"][0]
    assert gap["closed_by_engine"] is False
    assert gap["evidence"]["end_zone"] == "interior"
    assert gap["evidence"]["next_start_zone"] == "interior"


def test_istirahat_asli_dan_berbalik_lama_beda_hanya_di_zona():
    """Kalau UI menampilkan keduanya sebagai angka menit yang sama, seluruh
    kehati-hatian §4 hilang di lapisan terakhir. Tes ini mengunci bahwa
    perbedaannya memang ada di data, bukan cuma di niat."""
    _, palsu = emit(SCENARIO_DIR / "02-berbalik-lama.yaml")
    _, asli = emit(SCENARIO_DIR / "03-istirahat-asli.yaml")

    gap_palsu = build_expected(load(SCENARIO_DIR / "02-berbalik-lama.yaml"), palsu)["gaps"][0]
    gap_asli = build_expected(load(SCENARIO_DIR / "03-istirahat-asli.yaml"), asli)["gaps"][0]

    assert gap_palsu["evidence"]["end_zone"] == "interior"
    assert gap_asli["evidence"]["end_zone"] == "door"
    assert gap_palsu["closed_by_engine"] is gap_asli["closed_by_engine"] is False


def test_kamera_mati_tidak_ada_yang_pulang():
    _, messages = emit(SCENARIO_DIR / "04-kamera-mati.yaml")
    intervals = intervals_of(messages)
    ends = [p for c, p in messages if p["type"] == "track.ended"]

    assert len(intervals) == 3
    assert {i["end_reason"] for i in intervals} == {"camera_lost"}
    assert {i["end_source"] for i in intervals} == {"forced"}
    assert {e["reason"] for e in ends} == {"camera_lost"}


def test_identitas_tertukar_satu_track_dua_interval():
    _, messages = emit(SCENARIO_DIR / "05-identitas-tertukar.yaml")
    intervals = intervals_of(messages)
    assert len(intervals) == 2
    assert intervals[0]["person_id"] != intervals[1]["person_id"]
    assert intervals[0]["end_reason"] == "identity_released"
    # Dua interval, satu track: id-nya wajib berbeda.
    assert intervals[0]["interval_id"] != intervals[1]["interval_id"]
    assert intervals[0]["track_uuid"] == intervals[1]["track_uuid"]


def test_stitching_membawa_prev_interval_id():
    _, messages = emit(SCENARIO_DIR / "12-stitching.yaml")
    intervals = intervals_of(messages)
    assert len(intervals) == 2
    assert intervals[1]["prev_interval_id"] == intervals[0]["interval_id"]


def test_kamera_reconnect_pts_mundur_tapi_jam_dinding_maju():
    """Inti kenapa `stream_epoch` ada."""
    _, messages = emit(SCENARIO_DIR / "13-kamera-reconnect.yaml")
    intervals = intervals_of(messages)
    assert len(intervals) == 2
    awal, akhir = intervals

    assert akhir["stream_epoch"] == awal["stream_epoch"] + 1
    assert akhir["start_pts"] < awal["end_pts"], "pts harus kembali ke nol setelah reconnect"
    assert akhir["start_at"] > awal["end_at"], "jam dinding tidak boleh ikut mundur"

    onlines = [p for c, p in messages if p["type"] == "camera.online"]
    assert len(onlines) == 2
    assert onlines[1]["pts_wallclock_offset"] > onlines[0]["pts_wallclock_offset"]


def test_lintas_ruangan_tidak_disambung_engine():
    scenario, messages = emit(SCENARIO_DIR / "14-lintas-ruangan.yaml")
    expected = build_expected(scenario, messages)
    gap = expected["gaps"][0]
    assert gap["same_camera"] is False
    assert gap["closed_by_engine"] is False, (
        "penyambungan lintas kamera adalah penyambungan sesi, milik backend"
    )


def test_orang_tak_dikenal_tidak_menghasilkan_interval():
    _, messages = emit(SCENARIO_DIR / "08-orang-tak-dikenal.yaml")
    assert intervals_of(messages) == []
    alerts = [p for c, p in messages if p["type"] == "person.unidentified_present"]
    assert len(alerts) == 2


# --------------------------------------------------------------------------
# loader dan outbox
# --------------------------------------------------------------------------


def test_skenario_tidak_boleh_menulis_pesan_turunan():
    with pytest.raises(ScenarioError) as excinfo:
        from_mapping({
            "cameras": [{"id": "r1"}],
            "persons": ["1"],
            "timeline": [{"at": 1.0, "emit": "presence.interval"}],
        })
    assert "diturunkan otomatis" in str(excinfo.value)


def test_skenario_menolak_track_yang_belum_dibuka():
    with pytest.raises(ScenarioError):
        from_mapping({
            "cameras": [{"id": "r1"}],
            "persons": ["1"],
            "timeline": [{"at": 1.0, "emit": "track.ended", "track": "hantu"}],
        })


def test_skenario_menolak_orang_di_luar_roster():
    with pytest.raises(ScenarioError):
        from_mapping({
            "cameras": [{"id": "r1"}],
            "persons": ["1"],
            "timeline": [
                {"at": 0.0, "emit": "track.started", "track": "t1", "camera": "r1"},
                {"at": 1.0, "emit": "track.identified", "track": "t1", "person": "999"},
            ],
        })


def test_outbox_replay_dan_lubang():
    outbox = Outbox()
    for seq in range(1, 21):
        outbox.append({"type": "track.heartbeat", "seq": seq})

    assert [e["seq"] for e in outbox.since(17)] == [18, 19, 20]

    outbox.trim(keep_from_seq=12)
    assert outbox.oldest_available_seq == 12
    # Backend yang tertinggal di seq 5 tidak bisa dilayani penuh: itu lubang,
    # dan diam-diam mengirim sisanya berarti backend mengira tidak ada kejadian.
    assert outbox.oldest_available_seq - 1 > 5
