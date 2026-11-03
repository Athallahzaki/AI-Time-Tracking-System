"""P8: klaim wajah lintas kamera.

Keputusan tim: bersamaan di dua kamera sah bila bidang pandangnya bertumpang-tindih
(kamera kedua = bukti penguat). Selain itu skor wajah tertinggi menang; seri = pemegang
lama; yang kalah kembali tidak dikenal, dilepas di thread kameranya sendiri.
"""
from __future__ import annotations

import pytest

from engine.identity import Evidence, IdentityArbiter, InMemoryReferenceStore, MatrixMatcher, Outcome
from engine.identity.cross_camera import CrossCameraClaims
from engine.tests.test_identity import ALICE, BOB, jitter


def _arbiters(cross):
    matcher = MatrixMatcher(InMemoryReferenceStore({"alice": [ALICE], "bob": [BOB]}), threshold=0.37, margin=0.06)
    make = lambda: IdentityArbiter(matcher, min_evidence=3, min_spread_seconds=0.5, window=5,  # noqa: E731
                                   cross_camera=cross)
    return make(), make()


def _identify(arbiter, track, camera, amount, start=0.0):
    decision = None
    for index, pts in enumerate((start, start + 0.3, start + 0.6)):
        evidence = Evidence(jitter(ALICE, index, amount), pts, 0.9, "test-v1")
        decision = arbiter.observe(track, camera, evidence)
    return decision


def test_tanpa_registry_perilaku_lama_dua_kamera_sama_sama_mengklaim():
    a, b = _arbiters(None)
    assert _identify(a, "tr_a", "cam_a", 0.40).outcome is Outcome.IDENTIFIED
    assert _identify(b, "tr_b", "cam_b", 0.15).outcome is Outcome.IDENTIFIED


def test_klaim_lebih_kuat_di_kamera_lain_mencabut_yang_lemah_lewat_tick_pemiliknya():
    cross = CrossCameraClaims()
    a, b = _arbiters(cross)
    assert _identify(a, "tr_a", "cam_a", 0.40).outcome is Outcome.IDENTIFIED
    assert _identify(b, "tr_b", "cam_b", 0.15).outcome is Outcome.IDENTIFIED   # skor lebih tinggi
    assert a.identity_of("tr_a").person_id == "alice", "kamera lain tidak menyentuh arbiter A"

    released = [d for d in a.tick(1.0) if d.outcome is Outcome.IDENTITY_RELEASED]
    assert [(d.from_person_id, d.reason) for d in released] == [("alice", "cross_camera_lost_claim")]
    assert a.identity_of("tr_a").person_id is None, "yang kalah kembali tidak dikenal"
    assert b.identity_of("tr_b").person_id == "alice"
    assert cross.metrics() == {"cross_corroborated": 0, "cross_evicted": 1, "cross_rejected": 0}
    assert not [d for d in a.tick(1.1) if d.outcome is Outcome.IDENTITY_RELEASED], "sekali saja"


def test_klaim_lebih_lemah_ditolak_pemegang_tetap():
    cross = CrossCameraClaims()
    a, b = _arbiters(cross)
    _identify(a, "tr_a", "cam_a", 0.15)
    decision = _identify(b, "tr_b", "cam_b", 0.40)
    assert decision.outcome is Outcome.NOTHING and decision.reason == "cross_camera_lost_claim"
    assert b.identity_of("tr_b").person_id is None
    assert not a.tick(1.0) or all(d.outcome is not Outcome.IDENTITY_RELEASED for d in a.tick(1.0))
    assert a.identity_of("tr_a").person_id == "alice"


def test_kamera_tumpang_tindih_menjadi_bukti_penguat():
    cross = CrossCameraClaims([["cam_a", "cam_b"]])
    a, b = _arbiters(cross)
    assert _identify(a, "tr_a", "cam_a", 0.40).outcome is Outcome.IDENTIFIED
    assert _identify(b, "tr_b", "cam_b", 0.15).outcome is Outcome.IDENTIFIED
    assert not [d for d in a.tick(1.0) if d.outcome is Outcome.IDENTITY_RELEASED]
    assert cross.metrics()["cross_corroborated"] == 1


def test_track_ditutup_membebaskan_klaim_untuk_kamera_lain():
    cross = CrossCameraClaims()
    a, b = _arbiters(cross)
    _identify(a, "tr_a", "cam_a", 0.15)
    a.close_track("tr_a")                                  # orangnya keluar dari kamera A
    assert _identify(b, "tr_b", "cam_b", 0.40, start=5.0).outcome is Outcome.IDENTIFIED


def test_klaim_yang_dicabut_tidak_hidup_lagi_lewat_refresh():
    cross = CrossCameraClaims()
    assert cross.claim("cam_a", "tr_a", "alice", 0.6)
    assert cross.claim("cam_b", "tr_b", "alice", 0.9)
    cross.refresh("cam_a", "tr_a", "alice", 0.99)            # A belum sempat tick
    assert cross.take_evicted({"tr_a"}) == {"tr_a"}
    assert cross.claim("cam_c", "tr_c", "alice", 0.95)       # mengalahkan B, bukan A yang sudah dicabut
    assert cross.take_evicted({"tr_a", "tr_b"}) == {"tr_b"}


def test_seri_pemegang_lama_menang_dan_pasangan_tidak_valid_ditolak():
    cross = CrossCameraClaims()
    assert cross.claim("cam_a", "tr_a", "alice", 0.8)
    assert not cross.claim("cam_b", "tr_b", "alice", 0.8)
    with pytest.raises(ValueError):
        CrossCameraClaims([["cam_a", "cam_a"]])


def test_config_default_mati():
    from engine.config.schema import RecognitionConfig

    assert RecognitionConfig().cross_camera_claims is False
    assert RecognitionConfig().overlapping_cameras == ()
