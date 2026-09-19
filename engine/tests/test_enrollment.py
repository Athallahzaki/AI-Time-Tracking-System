"""Tes enrollment (A8).

Referensi buruk merusak permanen sementara frame buruk merusak satu percobaan,
jadi tes di sini semuanya tentang apa yang harus DITOLAK. Yang paling penting
dua terakhir: tanpa uji tabrakan, dua orang mirip akan tertukar selamanya, dan
tidak ada threshold atau margin di runtime yang bisa memperbaikinya — margin
test justru akan menolak keduanya, jadi keduanya jadi tidak bisa dikenali sama
sekali.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pytest

from contracts.validator import SchemaValidator
from engine.identity import InMemoryReferenceStore, MatrixMatcher
from engine.identity.enrollment import (
    EnrollmentPolicy,
    ImageCandidate,
    QualityGate,
    estimate_yaw,
)
from engine.store import SqliteReferenceStore

DIM = 64
JPEG = b"\xff\xd8\xff\xe0bukan-kosong"

FRONTAL = [[40.0, 50.0], [80.0, 50.0], [60.0, 70.0], [45.0, 90.0], [75.0, 90.0]]
PROFIL = [[40.0, 50.0], [80.0, 50.0], [95.0, 70.0], [45.0, 90.0], [75.0, 90.0]]


def unit(seed: int) -> np.ndarray:
    vector = np.random.default_rng(seed).normal(size=DIM).astype(np.float32)
    return vector / np.linalg.norm(vector)


def blend(a, b, t):
    mixed = (1.0 - t) * a + t * b
    return (mixed / np.linalg.norm(mixed)).astype(np.float32)


def good(image_id: str, embedding=None, **overrides) -> ImageCandidate:
    base = dict(
        image_id=image_id, face_count=1, embedding=embedding if embedding is not None else unit(1),
        jpeg=JPEG, face_width=160.0, face_height=160.0, sharpness=300.0,
        brightness=128.0, contrast=60.0, detector_confidence=0.95,
        landmarks=FRONTAL, camera_id="r1", captured_at="2026-09-19T02:15:31.200Z",
    )
    base.update(overrides)
    return ImageCandidate(**base)


def three_of(person_vector, prefix="img", **overrides):
    """Tiga foto yang berbeda cukup untuk lolos uji keberagaman.

    Deraunya 0,30 bukan angka sembarang: di bawah itu ketiganya saling di atas
    ambang duplikat 0,90 dan ditolak — yang memang perilaku yang benar, dan
    persis yang uji keberagaman ada untuk menangkap. Kalau nanti menyetel
    ambang itu dengan embedding sungguhan, ingat bahwa dua foto orang yang sama
    dari sesi berbeda wajar berada di 0,85-0,95.
    """
    return [
        good(f"{prefix}{index}", blend(person_vector, unit(500 + index), 0.30), **overrides)
        for index in range(1, 4)
    ]


def policy(references=None, **kwargs):
    store = InMemoryReferenceStore(references or {})
    matcher = MatrixMatcher(store, threshold=0.37, margin=0.06)
    return EnrollmentPolicy(matcher, **kwargs)


# --------------------------------------------------------------------------
# gerbang mutu per gambar
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides,expected",
    [
        ({"face_width": 60.0, "face_height": 60.0}, "too_small"),
        ({"sharpness": 10.0}, "blurry"),
        ({"landmarks": PROFIL}, "extreme_pose"),
        ({"brightness": 250.0}, "bad_lighting"),
        ({"contrast": 5.0}, "bad_lighting"),
        ({"face_count": 0, "embedding": None}, "no_face"),
        ({"face_count": 2}, "multiple_faces"),
        ({"detector_confidence": 0.55}, "low_confidence"),
    ],
    ids=lambda value: str(value)[:28],
)
def test_gerbang_menolak_dengan_alasan_spesifik(overrides, expected):
    """Alasan per gambar, bukan sekadar gagal: orang HRD yang mengunggah lima
    foto harus tahu foto mana yang salah dan kenapa."""
    assert QualityGate().evaluate(good("img1", **overrides)) == expected


def test_gerbang_meloloskan_foto_yang_layak():
    assert QualityGate().evaluate(good("img1")) is None


def test_gerbang_enrollment_lebih_ketat_daripada_runtime():
    """Referensi buruk merusak permanen; frame buruk merusak satu percobaan."""
    marginal = good("img1", detector_confidence=0.6)
    assert QualityGate().evaluate(marginal) == "low_confidence"
    assert QualityGate(min_detector_confidence=0.5).evaluate(marginal) is None


def test_yaw_dari_landmark():
    assert abs(estimate_yaw(FRONTAL)) < 0.1
    assert abs(estimate_yaw(PROFIL)) > 0.5
    assert estimate_yaw(None) is None


# --------------------------------------------------------------------------
# uji keberagaman
# --------------------------------------------------------------------------


def test_foto_yang_terlalu_mirip_ditolak_sebagai_duplikat():
    """Lima foto dari sesi yang sama dengan pose identik adalah satu referensi
    efektif yang menyamar jadi lima."""
    alice = unit(1)
    kandidat = [good("img1", alice), good("img2", alice), good("img3", alice)]

    result = policy().evaluate("4471", 1, kandidat)

    ditolak = [v for v in result.images if not v.accepted]
    assert [v.reason for v in ditolak] == ["duplicate_of:img1", "duplicate_of:img1"]
    assert result.reason == "insufficient_references"
    assert result.accepted is False


def test_syarat_minimal_tiga_referensi_tidak_bisa_dipenuhi_satu_momen():
    """Ini akibat sebenarnya dari uji keberagaman: tanpa itu, syarat 'minimal
    tiga' terpenuhi di atas kertas oleh satu momen tunggal."""
    alice = unit(1)
    kandidat = [good(f"img{i}", alice) for i in range(1, 6)]

    result = policy().evaluate("4471", 1, kandidat)

    assert len(result.accepted_images) == 1
    assert result.reason == "insufficient_references"


def test_foto_buram_tidak_bisa_memakan_foto_bagus_sebagai_duplikat():
    """Uji keberagaman hanya membandingkan terhadap yang sudah lolos mutu."""
    alice = unit(1)
    kandidat = [good("buram", alice, sharpness=5.0)] + three_of(alice)

    result = policy().evaluate("4471", 1, kandidat)

    assert result.accepted is True
    assert [v.image_id for v in result.accepted_images] == ["img1", "img2", "img3"]


def test_kurang_dari_tiga_yang_lolos_ditolak():
    alice = unit(1)
    kandidat = three_of(alice)[:2]
    result = policy().evaluate("4471", 1, kandidat)
    assert result.reason == "insufficient_references"


# --------------------------------------------------------------------------
# uji tabrakan
# --------------------------------------------------------------------------


def test_karyawan_yang_terlalu_mirip_karyawan_lain_ditolak():
    """Tanpa ini, keduanya tertukar selamanya — dan margin test di runtime
    justru membuat keduanya tidak bisa dikenali sama sekali."""
    alice = unit(1)
    kembar = blend(alice, unit(9), 0.05)

    p = policy({"4471": [alice]})
    result = p.evaluate("4802", 1, three_of(kembar))

    assert result.accepted is False
    assert result.reason == "collision"
    assert result.collides_with == "4471"
    assert result.collision_similarity > 0.4


def test_orang_yang_cukup_berbeda_diterima():
    p = policy({"4471": [unit(1)]})
    result = p.evaluate("4802", 1, three_of(unit(2)))

    assert result.accepted is True
    assert result.reason == "ok"
    assert result.collides_with is None


def test_mendaftar_ulang_orang_yang_sama_bukan_tabrakan():
    """Foto baru yang sangat mirip referensi lama justru tanda enrollment-nya
    benar. Menghitungnya sebagai tabrakan membuat re-enrollment mustahil."""
    alice = unit(1)
    p = policy({"4471": [alice]})

    result = p.evaluate("4471", 2, three_of(alice))

    assert result.accepted is True
    assert result.reason == "ok"


def test_roster_kosong_tidak_pernah_bertabrakan():
    result = policy().evaluate("4471", 1, three_of(unit(1)))
    assert result.accepted is True


# --------------------------------------------------------------------------
# peringatan, pesan, dan penulisan
# --------------------------------------------------------------------------


def test_referensi_yang_semuanya_pas_foto_diperingatkan():
    """Domain gap antara pas foto studio dan kamera sudut ruangan tidak bisa
    ditutup threshold apa pun. Ini peringatan, bukan penolakan — kadang pas
    foto satu-satunya yang ada."""
    result = policy().evaluate("4471", 1, three_of(unit(1), camera_id=None))

    assert result.accepted is True
    assert "no_cctv_reference" in result.warnings


def test_referensi_dari_kamera_tidak_diperingatkan():
    result = policy().evaluate("4471", 1, three_of(unit(1)))
    assert result.warnings == []


def test_pesan_enroll_result_lolos_skema_kontrak():
    alice = unit(1)
    p = policy({"4471": [alice]})
    kembar = blend(alice, unit(9), 0.05)

    ditolak = p.evaluate("4802", 1, three_of(kembar))
    diterima = p.evaluate("5120", 1, three_of(unit(3)))
    campur = p.evaluate("5121", 1, three_of(unit(4)) + [good("jelek", unit(4), sharpness=3.0)])

    validator = SchemaValidator()
    for result in (ditolak, diterima, campur):
        message = result.to_message("e-8812", "auraface-v1", "2026-09-19T08:14:22.481Z")
        issues = validator.validate_message(message, expected_channel="control")
        assert issues == [], [str(issue) for issue in issues]


def test_penolakan_tidak_menulis_apa_pun_ke_store():
    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteReferenceStore(Path(tmp) / "refs.db", embedding_version="v1", dimension=DIM)
        p = policy()
        kandidat = three_of(unit(1))[:1]

        result = p.evaluate("4471", 1, kandidat)
        assert p.commit(result, store, kandidat) == []
        assert store.records() == []
        store.close()


def test_penerimaan_menulis_referensi_beserta_metadatanya():
    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteReferenceStore(Path(tmp) / "refs.db", embedding_version="v1", dimension=DIM)
        p = policy()
        kandidat = three_of(unit(1))

        result = p.evaluate("4471", 3, kandidat)
        written = p.commit(result, store, kandidat)

        assert len(written) == 3
        records = store.records("4471")
        assert {record.enrollment_version for record in records} == {3}
        assert all(record.from_cctv for record in records)
        assert all(record.quality > 0 for record in records)
        store.close()
