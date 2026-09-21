"""Tes perakit interval kehadiran (A5 + tulang punggung A6).

Inilah pertama kalinya siklus hidup track, keputusan identitas, dan pesan
protokol bertemu di satu tempat. Jadi tes di sini bukan cuma memeriksa fungsi —
ia memeriksa bahwa aliran yang dihasilkan **lolos validator kontrak yang sama**
dengan yang dipakai untuk engine palsu. Engine asli yang memancarkan sesuatu
yang engine palsu tidak pernah memancarkan adalah ketidakcocokan yang baru
ketahuan di M3.
"""

from __future__ import annotations

from typing import List

import pytest

from contracts.validator import ConformanceChecker, SchemaValidator
from engine.presence import PresenceAssembler, ZoneLabeller

OFFSET = 1758240000.0
DOOR = {"r1": [0.62, 0.10, 0.95, 0.55], "r2": [0.05, 0.10, 0.35, 0.55]}

DI_PINTU = [0.70, 0.20, 0.85, 0.50]
DI_TENGAH = [0.40, 0.30, 0.55, 0.80]
DI_TEPI = [0.00, 0.30, 0.10, 0.80]


def build(stitch_window: float = 5.0):
    keluaran: List[dict] = []
    assembler = PresenceAssembler(
        emit=keluaran.append,
        zones=ZoneLabeller(DOOR),
        stitch_window_seconds=stitch_window,
    )
    return assembler, keluaran


def jenis(keluaran, message_type):
    return [message for message in keluaran if message["type"] == message_type]


def intervals(keluaran):
    return jenis(keluaran, "presence.interval")


def masuk_dan_dikenali(assembler, track, camera="r1", start=10.0, identified=12.4,
                       person="4471", bbox=DI_PINTU):
    assembler.track_started(track, camera, pts=start, bbox=bbox)
    assembler.identified(track, person, pts=identified, similarity=0.91,
                         margin=0.17, evidence_count=3, confidence=0.9)


# --------------------------------------------------------------------------
# zona
# --------------------------------------------------------------------------


def test_zona_dilabeli_dari_door_region():
    labeller = ZoneLabeller(DOOR)
    assert labeller.label("r1", DI_PINTU) == "door"
    assert labeller.label("r1", DI_TENGAH) == "interior"
    assert labeller.label("r1", DI_TEPI) == "frame_edge"


def test_kamera_tanpa_door_region_default_ke_interior():
    """Menebak `door` untuk kamera yang belum dikonfigurasi berarti diam-diam
    menandai setiap celah sebagai kepergian nyata — arah kesalahan yang
    menghasilkan surat peringatan."""
    labeller = ZoneLabeller({})
    assert labeller.label("r9", DI_PINTU) == "interior"


def test_door_region_piksel_ditolak():
    with pytest.raises(ValueError):
        ZoneLabeller({"r1": [100, 50, 400, 300]})


# --------------------------------------------------------------------------
# batas interval
# --------------------------------------------------------------------------


def test_interval_mulai_saat_track_lahir_bukan_saat_wajah_terbaca():
    """Selisihnya dicuri dari jatah tiga puluh menit oleh latensi pengenalan,
    bukan oleh orangnya."""
    assembler, keluaran = build()
    assembler.camera_online("r1", OFFSET, fps=10.0)
    masuk_dan_dikenali(assembler, "tr_1", start=10.0, identified=18.0)
    assembler.track_ended("tr_1", pts=300.0, reason="left_frame", zone="door")

    interval = intervals(keluaran)[0]
    assert interval["start_pts"] == 10.0, "bukan 18.0"
    assert jenis(keluaran, "track.identified")[0]["track_started_pts"] == 10.0


def test_track_tanpa_identitas_tidak_menghasilkan_interval():
    """Tanpa identitas tidak ada kehadiran yang bisa dicatat atas nama siapa
    pun. Tapi orangnya ADA — itu urusan person.unidentified_present."""
    assembler, keluaran = build()
    assembler.camera_online("r1", OFFSET, fps=10.0)
    assembler.track_started("tr_1", "r1", pts=10.0, bbox=DI_TENGAH)
    assembler.track_ended("tr_1", pts=200.0, reason="left_frame", zone="door")

    assert intervals(keluaran) == []
    assert assembler.metrics.unidentified_closed == 1


def test_zona_berakhir_diambil_dari_posisi_terakhir_yang_terlihat():
    """Track berakhir justru karena tidak terlihat lagi, jadi bbox saat
    berakhir sering tidak ada. Zona terakhir diingat selagi masih terlihat."""
    assembler, keluaran = build()
    assembler.camera_online("r1", OFFSET, fps=10.0)
    masuk_dan_dikenali(assembler, "tr_1", bbox=DI_PINTU)
    assembler.track_moved("tr_1", DI_TENGAH)
    assembler.track_ended("tr_1", pts=300.0, reason="occluded_timeout")

    interval = intervals(keluaran)[0]
    assert interval["start_zone"] == "door"
    assert interval["end_zone"] == "interior", "celah palsu harus bisa dikenali dari sini"


def test_identitas_dicabut_di_tengah_track_menghasilkan_dua_interval():
    """Satu track, dua interval — persis kenapa interval_id bukan track_uuid."""
    assembler, keluaran = build()
    assembler.camera_online("r1", OFFSET, fps=10.0)
    masuk_dan_dikenali(assembler, "tr_1")
    assembler.identity_released("tr_1", pts=100.0)
    assembler.identified("tr_1", "4802", pts=110.0, similarity=0.88,
                         margin=0.12, evidence_count=3, confidence=0.88)
    assembler.track_ended("tr_1", pts=300.0, reason="left_frame", zone="door")

    dua = intervals(keluaran)
    assert len(dua) == 2
    assert dua[0]["end_reason"] == "identity_released"
    assert dua[0]["person_id"] != dua[1]["person_id"]
    assert dua[0]["interval_id"] != dua[1]["interval_id"]
    assert dua[0]["track_uuid"] == dua[1]["track_uuid"]


# --------------------------------------------------------------------------
# kamera putus
# --------------------------------------------------------------------------


def test_kamera_putus_tidak_membuat_siapa_pun_pulang():
    assembler, keluaran = build()
    assembler.camera_online("r1", OFFSET, fps=10.0)
    for index, person in enumerate(("4471", "4802", "5120")):
        masuk_dan_dikenali(assembler, f"tr_{index}", start=10.0 + index, person=person)

    assembler.camera_failed("r1", OFFSET + 400.0, pts=400.0)

    tiga = intervals(keluaran)
    assert len(tiga) == 3
    assert {i["end_reason"] for i in tiga} == {"camera_lost"}
    assert {i["end_source"] for i in tiga} == {"forced"}


def test_reconnect_menaikkan_epoch_dan_pts_kembali_nol():
    assembler, keluaran = build()
    assembler.camera_online("r1", OFFSET, fps=10.0)
    masuk_dan_dikenali(assembler, "tr_1")
    assembler.camera_failed("r1", OFFSET + 200.0, pts=200.0)
    assembler.camera_online("r1", OFFSET + 215.0, fps=10.0)
    masuk_dan_dikenali(assembler, "tr_2", start=15.0, identified=17.0, bbox=DI_TENGAH)
    assembler.track_ended("tr_2", pts=300.0, reason="left_frame", zone="door")

    awal, akhir = intervals(keluaran)
    assert akhir["stream_epoch"] == awal["stream_epoch"] + 1
    assert akhir["start_pts"] < awal["end_pts"], "pts kembali ke nol"
    assert akhir["start_at"] > awal["end_at"], "jam dinding tidak ikut mundur"


# --------------------------------------------------------------------------
# penyambungan (A5)
# --------------------------------------------------------------------------


def test_teroklusi_sebentar_disambung_lewat_prev_interval_id():
    assembler, keluaran = build(stitch_window=5.0)
    assembler.camera_online("r1", OFFSET, fps=10.0)
    masuk_dan_dikenali(assembler, "tr_1", start=6.0, identified=7.0)
    assembler.track_moved("tr_1", DI_TENGAH)
    assembler.track_ended("tr_1", pts=150.0, reason="occluded_timeout")

    assembler.track_started("tr_2", "r1", pts=153.0, bbox=DI_TENGAH)
    assembler.identified("tr_2", "4471", pts=153.5, similarity=0.86,
                         margin=0.10, evidence_count=3, confidence=0.86)
    assembler.track_ended("tr_2", pts=420.0, reason="left_frame", zone="door")

    dua = intervals(keluaran)
    assert len(dua) == 2
    assert dua[1]["prev_interval_id"] == dua[0]["interval_id"]
    assert dua[1]["start_source"] == "tracking"

    resumed = jenis(keluaran, "track.resumed")
    assert len(resumed) == 1
    assert resumed[0]["prev_track_uuid"] == "tr_1"
    assert resumed[0]["gap_seconds"] == pytest.approx(3.0)
    assert assembler.metrics.stitches == 1


def test_jeda_lebih_lama_dari_jendela_tidak_disambung():
    assembler, keluaran = build(stitch_window=5.0)
    assembler.camera_online("r1", OFFSET, fps=10.0)
    masuk_dan_dikenali(assembler, "tr_1", start=6.0, identified=7.0)
    assembler.track_ended("tr_1", pts=150.0, reason="occluded_timeout", zone="interior")

    assembler.track_started("tr_2", "r1", pts=345.0, bbox=DI_TENGAH)
    assembler.identified("tr_2", "4471", pts=346.0, similarity=0.86,
                         margin=0.10, evidence_count=3, confidence=0.86)
    assembler.track_ended("tr_2", pts=600.0, reason="left_frame", zone="door")

    dua = intervals(keluaran)
    assert dua[1].get("prev_interval_id") is None
    assert jenis(keluaran, "track.resumed") == []


def test_penyambungan_tidak_lintas_kamera():
    """Lintas ruangan itu handoff — penyambungan sesi milik backend, bukan
    bukti perseptual milik engine."""
    assembler, keluaran = build(stitch_window=30.0)
    assembler.camera_online("r1", OFFSET, fps=10.0)
    assembler.camera_online("r2", OFFSET, fps=10.0)

    masuk_dan_dikenali(assembler, "tr_1", camera="r1", start=10.0, identified=12.0)
    assembler.track_ended("tr_1", pts=180.0, reason="left_frame", zone="door")

    assembler.track_started("tr_2", "r2", pts=188.0, bbox=[0.10, 0.20, 0.25, 0.50])
    assembler.identified("tr_2", "4471", pts=189.0, similarity=0.90,
                         margin=0.16, evidence_count=3, confidence=0.9)
    assembler.track_ended("tr_2", pts=600.0, reason="left_frame", zone="door")

    assert jenis(keluaran, "track.resumed") == []
    assert intervals(keluaran)[1].get("prev_interval_id") is None


def test_penyambungan_tidak_lintas_stream_epoch():
    """Setelah reconnect, pts kembali nol sehingga jedanya tidak bisa dihitung,
    dan tracker kehilangan seluruh state-nya. Bukti perseptualnya sudah tidak
    ada, jadi menyambung di situ adalah tebakan yang menyamar sebagai
    pengamatan."""
    assembler, keluaran = build(stitch_window=600.0)
    assembler.camera_online("r1", OFFSET, fps=10.0)
    masuk_dan_dikenali(assembler, "tr_1", start=10.0, identified=12.0)
    assembler.camera_failed("r1", OFFSET + 100.0, pts=100.0)

    assembler.camera_online("r1", OFFSET + 102.0, fps=10.0)
    assembler.track_started("tr_2", "r1", pts=1.0, bbox=DI_TENGAH)
    assembler.identified("tr_2", "4471", pts=2.0, similarity=0.9,
                         margin=0.15, evidence_count=3, confidence=0.9)
    assembler.track_ended("tr_2", pts=300.0, reason="left_frame", zone="door")

    assert jenis(keluaran, "track.resumed") == []


def test_penyambungan_hanya_untuk_orang_yang_sama():
    assembler, keluaran = build(stitch_window=30.0)
    assembler.camera_online("r1", OFFSET, fps=10.0)
    masuk_dan_dikenali(assembler, "tr_1", start=10.0, identified=12.0, person="4471")
    assembler.track_ended("tr_1", pts=150.0, reason="occluded_timeout", zone="interior")

    assembler.track_started("tr_2", "r1", pts=153.0, bbox=DI_TENGAH)
    assembler.identified("tr_2", "4802", pts=154.0, similarity=0.9,
                         margin=0.15, evidence_count=3, confidence=0.9)
    assembler.track_ended("tr_2", pts=400.0, reason="left_frame", zone="door")

    assert jenis(keluaran, "track.resumed") == []


def test_jendela_penyambungan_bisa_disetel_tanpa_menyentuh_kode():
    """Nilai N keluar dari rekaman B1. Sampai angkanya ada, yang penting ia
    parameter dan bukan konstanta yang tertanam di logika."""
    for window, harus_tersambung in ((2.0, False), (10.0, True)):
        assembler, keluaran = build(stitch_window=window)
        assembler.camera_online("r1", OFFSET, fps=10.0)
        masuk_dan_dikenali(assembler, "tr_1", start=6.0, identified=7.0)
        assembler.track_ended("tr_1", pts=150.0, reason="occluded_timeout", zone="interior")
        assembler.track_started("tr_2", "r1", pts=155.0, bbox=DI_TENGAH)
        assembler.identified("tr_2", "4471", pts=155.5, similarity=0.86,
                             margin=0.1, evidence_count=3, confidence=0.86)
        assembler.track_ended("tr_2", pts=300.0, reason="left_frame", zone="door")

        tersambung = bool(jenis(keluaran, "track.resumed"))
        assert tersambung is harus_tersambung, f"jendela {window}s"


# --------------------------------------------------------------------------
# kesesuaian kontrak
# --------------------------------------------------------------------------


def test_seluruh_aliran_lolos_skema_dan_aturan_aliran():
    """Validator yang sama dengan yang dipakai untuk fake_engine."""
    assembler, keluaran = build()
    assembler.camera_online("r1", OFFSET, fps=10.0)
    masuk_dan_dikenali(assembler, "tr_1", start=6.0, identified=7.0)
    assembler.track_moved("tr_1", DI_TENGAH)
    assembler.track_ended("tr_1", pts=150.0, reason="occluded_timeout")
    assembler.track_started("tr_2", "r1", pts=152.0, bbox=DI_TENGAH)
    assembler.identified("tr_2", "4471", pts=152.5, similarity=0.86,
                         margin=0.1, evidence_count=3, confidence=0.86)
    assembler.track_ended("tr_2", pts=400.0, reason="left_frame", zone="door")
    assembler.camera_failed("r1", OFFSET + 401.0, pts=401.0)

    validator = SchemaValidator()
    for index, message in enumerate(keluaran, start=1):
        message["seq"] = index
        issues = validator.validate_message(message, line=index, expected_channel="events")
        assert issues == [], f"{message['type']}: {[str(i) for i in issues]}"

    report = ConformanceChecker().check(
        [dict(m, _line=i) for i, m in enumerate(keluaran, start=1)]
    )
    assert report.errors == [], "\n".join(str(error) for error in report.errors)
