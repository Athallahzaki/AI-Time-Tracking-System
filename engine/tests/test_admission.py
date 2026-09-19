"""Tes penjadwalan pengenalan dan penolakan bukti berlebihan (A3).

Yang diuji di sini adalah hal-hal yang tidak pernah muncul sebagai error dan
tidak pernah terlihat di dashboard: antrian yang meledak, wajah yang selalu
dikenali dari posisi yang sudah ditinggalkan, satu kamera ramai yang membuat
empat kamera lain buta, dan `evidence_count` yang naik tanpa informasi naik.
"""

from __future__ import annotations

import numpy as np

from engine.identity import (
    Evidence,
    EvidenceWindow,
    IdentityArbiter,
    IdentityState,
    InMemoryReferenceStore,
    MatrixMatcher,
    Priority,
    RecognitionScheduler,
    TrackIdentity,
)

DIM = 64


def unit(seed: int) -> np.ndarray:
    vector = np.random.default_rng(seed).normal(size=DIM).astype(np.float32)
    return vector / np.linalg.norm(vector)


def blend(a: np.ndarray, b: np.ndarray, t: float) -> np.ndarray:
    mixed = (1.0 - t) * a + t * b
    return (mixed / np.linalg.norm(mixed)).astype(np.float32)


ALICE = unit(1)
BOB = unit(2)


def identity(state=IdentityState.PENDING, uuid="tr_1", camera="r1", last_face=None):
    return TrackIdentity(track_uuid=uuid, camera_id=camera, state=state, last_face_pts=last_face)


# --------------------------------------------------------------------------
# bukti berkorelasi (§9 butir 3)
# --------------------------------------------------------------------------


def test_bukti_yang_praktis_salinan_ditolak():
    """Sebaran waktu saja tidak menjamin bukti tidak berkorelasi. Orang yang
    duduk diam menghadap kamera menghasilkan frame yang sama persis satu detik
    kemudian — dua pengamatan yang dihitung dua kali padahal satu."""
    window = EvidenceWindow(window=5, min_evidence=3, min_spread_seconds=0.5)

    assert window.add(Evidence(ALICE, 0.0, 0.9)) is True
    assert window.add(Evidence(ALICE, 1.0, 0.9)) is False, "vektor identik tidak menambah informasi"
    assert window.add(Evidence(ALICE, 2.0, 0.9)) is False

    assert len(window) == 1
    assert window.rejected_redundant == 2
    assert not window.is_confirmable, "tiga percobaan, satu bukti — belum boleh terkonfirmasi"


def test_bukti_yang_cukup_berbeda_tetap_diterima():
    """Ambangnya harus tinggi. Dua foto wajah orang yang sama dari detik
    berbeda wajar berada di 0,90-0,96; menolak di situ membuat track yang
    orangnya menghadap kamera tidak pernah mengumpulkan cukup bukti."""
    window = EvidenceWindow(window=5, min_evidence=3, min_spread_seconds=0.5)

    assert window.add(Evidence(ALICE, 0.0, 0.9)) is True
    assert window.add(Evidence(blend(ALICE, unit(50), 0.15), 0.4, 0.9)) is True
    assert window.add(Evidence(blend(ALICE, unit(51), 0.18), 0.9, 0.9)) is True

    assert len(window) == 3
    assert window.is_confirmable


def test_bukti_berlebihan_tidak_mendorong_track_ke_held():
    """Ditolak karena berlebihan bukan berarti wajahnya tidak terlihat. Kalau
    penolakan ikut menghentikan `last_face_pts`, orang yang diam menatap kamera
    akan dianggap membelakanginya."""
    store = InMemoryReferenceStore({"alice": [ALICE], "bob": [BOB]})
    arbiter = IdentityArbiter(MatrixMatcher(store), min_evidence=3, min_spread_seconds=0.5)

    for pts in (0.0, 0.4, 0.9):
        arbiter.observe("tr_1", "r1", Evidence(blend(ALICE, unit(60 + int(pts * 10)), 0.12), pts, 0.9, "test-v1"))

    decision = arbiter.observe("tr_1", "r1", Evidence(ALICE, 5.0, 0.9, "test-v1"))
    arbiter.observe("tr_1", "r1", Evidence(ALICE, 5.5, 0.9, "test-v1"))

    arbiter.tick(6.0)
    assert arbiter.identity_of("tr_1").state is IdentityState.CONFIRMED
    assert decision.reason in {None, "redundant_evidence"}


# --------------------------------------------------------------------------
# antrian
# --------------------------------------------------------------------------


def test_track_yang_sedang_dikerjakan_tidak_mengantre_lagi():
    """Kebijakan lama menjawab "belum confirmed, kenali lagi" di setiap frame
    selama hasilnya belum kembali, dan antrian meledak dalam dua detik."""
    scheduler = RecognitionScheduler()
    scheduler.submit("tr_1", "r1", Priority.UNIDENTIFIED, 0.0)
    scheduler.pop(0.0)

    assert scheduler.in_flight == 1
    assert scheduler.submit("tr_1", "r1", Priority.UNIDENTIFIED, 0.1) is False
    assert scheduler.priority_for(identity(), now_pts=0.1) is None
    assert scheduler.depth == 0


def test_track_baru_di_pintu_mendahului_antrian():
    """Momen masuk pintu adalah satu-satunya saat wajah frontal hampir
    dijamin, karena pintu menghadap kamera sudut."""
    scheduler = RecognitionScheduler()
    scheduler.submit("tr_lama", "r1", Priority.REVERIFY, 0.0)
    scheduler.submit("tr_interior", "r1", Priority.UNIDENTIFIED, 0.01)
    scheduler.submit("tr_pintu", "r1", Priority.DOOR_NEW, 0.02)

    assert scheduler.pop(0.1).track_uuid == "tr_pintu"


def test_zona_pintu_menentukan_prioritas_track_baru():
    scheduler = RecognitionScheduler()
    assert scheduler.priority_for(None, 0.0, zone="door") is Priority.DOOR_NEW
    assert scheduler.priority_for(None, 0.0, zone="interior") is Priority.UNIDENTIFIED


def test_permintaan_basi_dibuang_dan_yang_terbaru_tidak_dikorbankan():
    """Dibuang berdasarkan UMUR, bukan posisi. Membuang permintaan terbaru demi
    mempertahankan yang lama berarti selalu mengenali wajah dari posisi yang
    sudah ditinggalkan orangnya."""
    scheduler = RecognitionScheduler(max_age_seconds=0.5)
    scheduler.submit("tr_lama", "r1", Priority.UNIDENTIFIED, 0.0)
    scheduler.submit("tr_baru", "r1", Priority.UNIDENTIFIED, 1.9)

    request = scheduler.pop(2.0)

    assert request is not None
    assert request.track_uuid == "tr_baru"
    assert scheduler.dropped_stale == 1


def test_satu_kamera_ramai_tidak_memonopoli():
    """Lima kamera, satu GPU. Tanpa kuota, ruangan tersibuk membuat empat
    ruangan lain tidak pernah dikenali sama sekali."""
    scheduler = RecognitionScheduler(per_camera_quota=2, max_age_seconds=100.0)
    for index in range(4):
        scheduler.submit(f"tr_r1_{index}", "r1", Priority.UNIDENTIFIED, 0.0)
    scheduler.submit("tr_r2", "r2", Priority.UNIDENTIFIED, 0.1)

    diambil = [scheduler.pop(0.2) for _ in range(3)]
    kamera = [request.camera_id for request in diambil if request]

    assert kamera.count("r1") == 2, "kuota per kamera harus menahan yang ketiga"
    assert "r2" in kamera, "kamera lain tetap kebagian"


def test_permintaan_ulang_menggantikan_yang_lama_bukan_menumpuk():
    scheduler = RecognitionScheduler(max_age_seconds=100.0)
    scheduler.submit("tr_1", "r1", Priority.UNIDENTIFIED, 0.0)
    scheduler.submit("tr_1", "r1", Priority.DOOR_NEW, 0.3)

    assert scheduler.depth == 1
    request = scheduler.pop(0.4)
    assert request.priority is Priority.DOOR_NEW
    assert request.requested_pts == 0.3, "crop yang lebih segar yang dipakai"


def test_backoff_setelah_percobaan_berulang_yang_gagal():
    """Punggung orang tidak akan berubah jadi wajah kalau dicoba tiap detik.
    Yang dibayar cuma GPU."""
    scheduler = RecognitionScheduler(
        retry_interval_seconds=1.0, backoff_interval_seconds=5.0, attempts_before_backoff=3,
        max_age_seconds=100.0,
    )
    pts = 0.0
    for _ in range(3):
        scheduler.submit("tr_1", "r1", Priority.UNIDENTIFIED, pts)
        scheduler.pop(pts)
        scheduler.complete("tr_1", produced_evidence=False)
        pts += 1.0

    assert scheduler.priority_for(identity(), now_pts=pts + 1.0) is None, "masih dalam backoff"
    assert scheduler.priority_for(identity(), now_pts=pts + 6.0) is not None


def test_percobaan_yang_menghasilkan_bukti_mereset_backoff():
    scheduler = RecognitionScheduler(attempts_before_backoff=2, max_age_seconds=100.0)
    for pts in (0.0, 1.0):
        scheduler.submit("tr_1", "r1", Priority.UNIDENTIFIED, pts)
        scheduler.pop(pts)
        scheduler.complete("tr_1", produced_evidence=False)

    scheduler.submit("tr_1", "r1", Priority.UNIDENTIFIED, 6.0)
    scheduler.pop(6.0)
    scheduler.complete("tr_1", produced_evidence=True)

    assert scheduler.priority_for(identity(), now_pts=7.5) is not None


def test_klaim_sehat_tidak_dicoba_ulang_sampai_jatuh_tempo():
    scheduler = RecognitionScheduler(reverify_interval_seconds=60.0)
    sehat = identity(state=IdentityState.CONFIRMED, last_face=100.0)
    sehat.person_id = "alice"

    assert scheduler.priority_for(sehat, now_pts=120.0) is None
    assert scheduler.priority_for(sehat, now_pts=170.0) is Priority.REVERIFY


def test_klaim_kedaluwarsa_didahulukan_daripada_pemeriksaan_berkala():
    scheduler = RecognitionScheduler()
    kedaluwarsa = identity(state=IdentityState.EXPIRED, uuid="tr_exp", last_face=0.0)
    dipegang = identity(state=IdentityState.HELD, uuid="tr_held", last_face=0.0)

    assert scheduler.priority_for(kedaluwarsa, now_pts=100.0) is Priority.EXPIRED
    assert scheduler.priority_for(dipegang, now_pts=100.0) is Priority.REVERIFY
    assert Priority.EXPIRED < Priority.REVERIFY


def test_melupakan_track_membersihkan_seluruh_jejaknya():
    scheduler = RecognitionScheduler(max_age_seconds=100.0)
    scheduler.submit("tr_1", "r1", Priority.UNIDENTIFIED, 0.0)
    scheduler.pop(0.0)
    scheduler.forget("tr_1")

    assert scheduler.in_flight == 0
    assert scheduler.depth == 0
    assert scheduler.priority_for(identity(), now_pts=0.1) is not None


def test_metrik_antrian_tersedia():
    """§5.2 menyebut empat metrik wajib. Diambil dari penjadwal karena di
    sinilah keputusannya dibuat; worker cuma menjalankannya."""
    scheduler = RecognitionScheduler(max_age_seconds=100.0)
    scheduler.submit("tr_1", "r1", Priority.UNIDENTIFIED, 0.0)
    scheduler.submit("tr_2", "r1", Priority.DOOR_NEW, 0.5)
    scheduler.pop(0.6)

    metrics = scheduler.metrics(1.0)
    assert metrics["queue_depth"] == 1.0
    assert metrics["in_flight"] == 1.0
    assert metrics["oldest_queued_age"] == 1.0
