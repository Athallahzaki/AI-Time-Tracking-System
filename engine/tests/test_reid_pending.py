"""ReID: identitas tertunda ANON-xxxx, resolusi wajah, dan purge harian (dokumen 12 §3.6)."""

from __future__ import annotations

import re

import numpy as np

from engine.identity.reid import BodyObservation, PendingIdentities, ReidConfig, TrackClosed

DIM = 32
DAY = "2026-10-09"
T0 = 1_791_500_000.0  # sekitar 9 Okt 2026
CFG = ReidConfig.from_mapping({
    "min_travel_seconds": {"lobby": {"biliar": 20, "smoking": 10, "luar": 8}},
})


def _vec(i: int, j: int = None, mix: float = 0.0) -> np.ndarray:
    v = np.zeros(DIM, dtype=np.float32)
    v[i] = 1.0
    if j is not None:
        v[j] = mix
    return v


def _obs(cam, tid, dt, emb=None, face=None, zone=None):
    return BodyObservation(camera_id=cam, track_id=tid, track_uuid=f"tr_{cam}_{tid}",
                           at=T0 + dt, embedding=emb, face_person_id=face, zone=zone)


def _core():
    return PendingIdentities(DAY, CFG)


def test_track_tanpa_wajah_mendapat_anon_dan_track_mirip_digabung():
    core = _core()
    a = core.observe(_obs("cam1", 1, 0, _vec(0), zone="lobby"))
    assert re.match(r"^ANON-[A-Za-z0-9]{1,32}$", a.person_id)
    assert a.identity_source == "reid"
    core.close(TrackClosed("cam1", "tr_cam1_1", T0 + 5))
    # Muncul lagi di lobby (pergantian ID tracker), penampilan sama.
    b = core.observe(_obs("cam1", 2, 6, _vec(0, 1, 0.1), zone="lobby"))
    assert b.person_id == a.person_id
    assert core.group_members(a.anon_id) == ("tr_cam1_1", "tr_cam1_2")


def test_dua_orang_mirip_di_kamera_berbeda_bersamaan_tidak_digabung():
    core = _core()
    a = core.observe(_obs("cam1", 1, 0, _vec(0), zone="lobby"))
    core.observe(_obs("cam1", 1, 30, zone="lobby"))          # masih hidup
    b = core.observe(_obs("cam5", 7, 20, _vec(0), zone="biliar"))  # embedding identik
    assert b.person_id != a.person_id
    assert b.person_id.startswith("ANON-")


def test_dua_orang_mirip_bersamaan_tidak_digabung_ke_karyawan_galeri():
    core = _core()
    core.observe(_obs("cam1", 1, 0, _vec(0), face="4471", zone="lobby"))
    core.observe(_obs("cam1", 1, 30, face="4471", zone="lobby"))
    b = core.observe(_obs("cam5", 7, 20, _vec(0), zone="biliar"))
    assert b.person_id != "4471"


def test_perpindahan_lebih_cepat_dari_waktu_tempuh_ditolak():
    core = _core()
    a = core.observe(_obs("cam2", 1, 0, _vec(0), zone="lobby"))
    core.close(TrackClosed("cam2", "tr_cam2_1", T0 + 10))
    cepat = core.observe(_obs("cam5", 3, 15, _vec(0), zone="biliar"))   # 5 dtk < 20
    assert cepat.person_id != a.person_id
    core.close(TrackClosed("cam5", "tr_cam5_3", T0 + 16))
    # Track lain, cukup lama sesudahnya, dari lokasi lain yang jauh dari keduanya.
    wajar = core.observe(_obs("cam2", 9, 60, _vec(0), zone="lobby"))
    # Mirip dengan dua kelompok sekaligus -> margin sempit -> tidak digabung.
    assert wajar.person_id not in (a.person_id, cepat.person_id)


def test_galeri_wajah_mengenali_track_tanpa_wajah_sesudah_waktu_tempuh():
    core = _core()
    core.observe(_obs("cam2", 1, 0, _vec(0), face="4471", zone="lobby"))
    core.observe(_obs("cam2", 1, 5, _vec(1), face="4471", zone="lobby"))  # tampak belakang
    core.close(TrackClosed("cam2", "tr_cam2_1", T0 + 10))
    b = core.observe(_obs("cam5", 4, 40, _vec(1, 2, 0.1), zone="biliar"))
    assert (b.person_id, b.identity_source) == ("4471", "reid")
    # Wajah tidak lagi terlihat di track asal: sumbernya tracking, bukan face.
    c = core.observe(_obs("cam2", 1, 9, zone="lobby"))
    assert (c.person_id, c.identity_source) == ("4471", "tracking")


def test_wajah_terkonfirmasi_menyelesaikan_seluruh_kelompok():
    core = _core()
    a = core.observe(_obs("cam1", 1, 0, _vec(3), zone="lobby"))
    core.close(TrackClosed("cam1", "tr_cam1_1", T0 + 4))
    core.observe(_obs("cam1", 2, 5, _vec(3), zone="lobby"))
    r = core.observe(_obs("cam1", 2, 8, _vec(3), face="5520", zone="lobby"))
    assert (r.person_id, r.identity_source) == ("5520", "face")
    (res,) = r.resolutions
    assert res.anon_id == a.anon_id and res.person_id == "5520"
    assert res.reason == "face_confirmed" and res.trigger_track_uuid == "tr_cam1_2"
    assert res.track_uuids == ("tr_cam1_1", "tr_cam1_2")
    fields = res.event_fields()
    assert fields["type"] == "identity.resolved"
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$", fields["at"])
    assert "moved_intervals" not in fields     # diisi lapisan presence
    assert core.identity_of("tr_cam1_1") == ("5520", "reid_retro")
    assert core.unresolved_anon_ids() == ()


def test_kelompok_lain_yang_cocok_ikut_diselesaikan_group_merged():
    core = _core()
    g1 = core.observe(_obs("cam4", 1, 0, _vec(5), zone="hiburan"))
    core.close(TrackClosed("cam4", "tr_cam4_1", T0 + 2))
    # Kelompok kedua: track wajah datang dari sudut berbeda, ANON tersendiri.
    g2 = core.observe(_obs("cam2", 2, 100, _vec(6), zone="lobby"))
    assert g1.anon_id != g2.anon_id
    r = core.observe(_obs("cam2", 2, 104, _vec(5), face="7001", zone="lobby"))
    reasons = sorted((x.anon_id, x.reason) for x in r.resolutions)
    assert reasons == sorted([(g2.anon_id, "face_confirmed"), (g1.anon_id, "group_merged")])
    assert core.identity_of("tr_cam4_1") == ("7001", "reid_retro")


def test_wajah_menang_dan_klaim_reid_yang_bertabrakan_dicabut():
    core = _core()
    core.observe(_obs("cam2", 1, 0, _vec(0), face="4471", zone="lobby"))
    core.close(TrackClosed("cam2", "tr_cam2_1", T0 + 1))
    b = core.observe(_obs("cam5", 4, 40, _vec(0), zone="biliar"))
    assert b.person_id == "4471"
    # Wajah 4471 terbaca di lobby saat track biliar masih hidup: ReID salah.
    core.observe(_obs("cam5", 4, 60, zone="biliar"))
    r = core.observe(_obs("cam2", 9, 50, _vec(0), face="4471", zone="lobby"))
    assert r.identity_source == "face"
    assert r.revoked == ("tr_cam5_4",)
    assert core.identity_of("tr_cam5_4") == (None, None)


def test_reid_tidak_pernah_membatalkan_wajah():
    core = _core()
    core.observe(_obs("cam1", 1, 0, _vec(0), face="4471", zone="lobby"))
    # Embedding track berwajah 5520 mirip galeri 4471: wajah tetap menang.
    r = core.observe(_obs("cam3", 2, 100, _vec(0), face="5520", zone="smoking"))
    assert (r.person_id, r.identity_source) == ("5520", "face")


def test_purge_harian_mengosongkan_galeri_dan_kelompok():
    core = _core()
    core.observe(_obs("cam1", 1, 0, _vec(0), face="4471", zone="lobby"))
    anon = core.observe(_obs("cam4", 2, 100, _vec(9), zone="hiburan")).anon_id
    report = core.purge_day("2026-10-10")
    assert report.day == DAY and report.persons_purged == 1
    assert report.unresolved_anon_ids == (anon,)
    assert len(core.gallery) == 0 and core.unresolved_anon_ids() == ()
    assert core.identity_of("tr_cam1_1") is None
    # Hari baru: tidak dikenali dari galeri kemarin, ID ANON tidak berulang.
    fresh = core.observe(_obs("cam1", 1, 90_000, _vec(0), zone="lobby"))
    assert fresh.person_id.startswith("ANON-") and fresh.person_id != anon


def test_pengamatan_tanpa_embedding_belum_memberi_identitas():
    core = _core()
    r = core.observe(_obs("cam1", 1, 0, zone="lobby"))
    assert (r.person_id, r.identity_source) == (None, None)
