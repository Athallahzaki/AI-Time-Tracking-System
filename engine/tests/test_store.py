"""Tes penyimpanan referensi.

Dua tes di berkas ini menjaga hal yang sama dari dua sisi, dan keduanya
tentang kegagalan yang tidak memunculkan error: vektor dari model lain yang
diam-diam ikut dicocokkan, dan gambar asli yang tidak disimpan sehingga
pergantian model berarti memanggil seluruh karyawan untuk foto ulang.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pytest

from engine.identity import MatrixMatcher
from engine.store import RosterDiff, SqliteReferenceStore, StoreError

DIM = 64
JPEG = b"\xff\xd8\xff\xe0palsu-tapi-bukan-kosong"


def unit(seed: int) -> np.ndarray:
    vector = np.random.default_rng(seed).normal(size=DIM).astype(np.float32)
    return vector / np.linalg.norm(vector)


def store(tmp: str, version: str = "auraface-v1") -> SqliteReferenceStore:
    return SqliteReferenceStore(Path(tmp) / "refs.db", embedding_version=version, dimension=DIM)


# --------------------------------------------------------------------------
# versi model
# --------------------------------------------------------------------------


def test_vektor_versi_lain_tidak_dikembalikan():
    """Cosine antara embedding dua model bukan angka yang salah — ia angka
    tanpa arti. Roster kosong setelah ganti model adalah kegagalan yang
    kelihatan; roster penuh vektor tak berarti adalah kegagalan yang tidak."""
    with tempfile.TemporaryDirectory() as tmp:
        s = store(tmp)
        s.add_reference("4471", unit(1), JPEG, quality=0.8)
        s.add_reference("4471", unit(2), JPEG, quality=0.8, embedding_version="model-lama-v0")

        assert len(s.references()["4471"]) == 1, "hanya versi sekarang yang boleh keluar"
        assert s.stats()["references_stale"] == 1
        s.close()


def test_ganti_model_mengosongkan_roster_tapi_gambar_tetap_ada():
    """Inilah alasan gambar asli disimpan. Tanpa ini, satu-satunya jalan
    keluar adalah memanggil seluruh karyawan untuk foto ulang."""
    with tempfile.TemporaryDirectory() as tmp:
        lama = store(tmp, version="auraface-v1")
        lama.add_reference("4471", unit(1), JPEG, quality=0.8)
        lama.add_reference("4471", unit(2), JPEG, quality=0.9)
        lama.close()

        baru = store(tmp, version="model-baru-v2")
        assert baru.references() == {}, "vektor lama tidak boleh dipakai"
        assert baru.pending_reembedding() == ["4471"]

        gambar = baru.images_for_reembedding("4471")
        assert len(gambar) == 2
        assert all(blob == JPEG for _, blob in gambar)

        for reference_id, _ in gambar:
            baru.attach_reembedding(reference_id, unit(7))

        assert len(baru.references()["4471"]) == 2
        assert baru.pending_reembedding() == []
        baru.close()


def test_referensi_lama_tidak_dihapus_saat_dihitung_ulang():
    """Kalau pergantian model ternyata memburukkan akurasi, jalan pulangnya
    harus masih ada."""
    with tempfile.TemporaryDirectory() as tmp:
        lama = store(tmp, version="v1")
        lama.add_reference("4471", unit(1), JPEG, quality=0.8)
        lama.close()

        baru = store(tmp, version="v2")
        baru.attach_reembedding(baru.images_for_reembedding("4471")[0][0], unit(9))

        versions = {record.embedding_version for record in baru.records("4471")}
        assert versions == {"v1", "v2"}
        baru.close()


# --------------------------------------------------------------------------
# gambar asli wajib
# --------------------------------------------------------------------------


def test_referensi_tanpa_gambar_ditolak():
    with tempfile.TemporaryDirectory() as tmp:
        s = store(tmp)
        with pytest.raises(StoreError, match="tanpa gambar asli"):
            s.add_reference("4471", unit(1), b"", quality=0.8)
        s.close()


def test_dimensi_salah_ditolak():
    with tempfile.TemporaryDirectory() as tmp:
        s = store(tmp)
        with pytest.raises(StoreError):
            s.add_reference("4471", np.zeros(DIM + 1, dtype=np.float32), JPEG, quality=0.8)
        s.close()


def test_vektor_disimpan_ternormalisasi():
    with tempfile.TemporaryDirectory() as tmp:
        s = store(tmp)
        s.add_reference("4471", unit(1) * 17.0, JPEG, quality=0.8)
        vector = s.references()["4471"][0]
        assert abs(float(np.linalg.norm(vector)) - 1.0) < 1e-5
        s.close()


# --------------------------------------------------------------------------
# rekonsiliasi roster
# --------------------------------------------------------------------------


def test_set_roster_membuang_orang_yang_tidak_ada_di_daftar():
    """Perintah imperatif akan desync begitu satu pesan hilang, dan kamu tidak
    akan tahu sampai ada vektor hantu yang masih dicocokkan padahal orangnya
    sudah keluar dari perusahaan."""
    with tempfile.TemporaryDirectory() as tmp:
        s = store(tmp)
        s.add_reference("4471", unit(1), JPEG, quality=0.8, enrollment_version=3)
        s.add_reference("4802", unit(2), JPEG, quality=0.8, enrollment_version=1)

        diff = s.set_roster({"4471": 3})

        assert diff.dropped == ("4802",)
        assert diff.unchanged == ("4471",)
        assert "4802" not in s.references()
        s.close()


def test_set_roster_meminta_enrollment_untuk_yang_belum_punya_vektor():
    with tempfile.TemporaryDirectory() as tmp:
        s = store(tmp)
        diff = s.set_roster({"4471": 1, "5120": 1})

        assert set(diff.needs_enrollment) == {"4471", "5120"}
        assert diff.dropped == ()
        s.close()


def test_versi_enrollment_naik_membuang_referensi_lama():
    """Versi naik berarti referensinya berubah. Membiarkan yang lama berarti
    pencocokan terhadap foto yang sudah dinyatakan usang."""
    with tempfile.TemporaryDirectory() as tmp:
        s = store(tmp)
        s.add_reference("4471", unit(1), JPEG, quality=0.8, enrollment_version=1)

        diff = s.set_roster({"4471": 2})

        assert diff.needs_enrollment == ("4471",)
        assert s.references() == {}
        s.close()


def test_penghapusan_orang_menghapus_vektor_dan_gambarnya():
    """Menyimpan vektor dan bukan foto bukan pembelaan privasi: template
    inversion bisa merekonstruksi wajah dari embedding ArcFace."""
    with tempfile.TemporaryDirectory() as tmp:
        s = store(tmp)
        s.add_reference("4471", unit(1), JPEG, quality=0.8)
        s.add_reference("4471", unit(2), JPEG, quality=0.8)

        assert s.delete_person("4471") == 2
        assert s.records("4471") == []
        assert s.stats()["image_bytes"] == 0
        s.close()


# --------------------------------------------------------------------------
# metadata dan integrasi
# --------------------------------------------------------------------------


def test_metadata_referensi_tersimpan():
    """Asal referensi bukan catatan administratif: pas foto studio dan kamera
    sudut ruangan punya domain gap yang tidak bisa ditutup threshold apa pun."""
    with tempfile.TemporaryDirectory() as tmp:
        s = store(tmp)
        s.add_reference("4471", unit(1), JPEG, quality=0.81,
                        camera_id="r1", captured_at="2026-09-19T02:15:31.200Z")
        s.add_reference("4471", unit(2), JPEG, quality=0.62)

        records = s.records("4471")
        assert records[0].from_cctv is True
        assert records[0].camera_id == "r1"
        assert records[0].quality == 0.81
        assert records[1].from_cctv is False, "pas foto harus bisa dibedakan"
        s.close()


def test_bertahan_setelah_dibuka_ulang():
    with tempfile.TemporaryDirectory() as tmp:
        first = store(tmp)
        first.add_reference("4471", unit(1), JPEG, quality=0.8)
        first.close()

        second = store(tmp)
        assert "4471" in second.references()
        second.close()


def test_store_ini_bisa_langsung_dipakai_matcher():
    """Kontraknya `engine.identity.ports.ReferenceStore`. Kalau tes ini gagal,
    lapisan identitas tidak punya sumber vektor yang persisten."""
    with tempfile.TemporaryDirectory() as tmp:
        s = store(tmp)
        alice, bob = unit(1), unit(2)
        s.add_reference("alice", alice, JPEG, quality=0.9)
        s.add_reference("bob", bob, JPEG, quality=0.9)

        matcher = MatrixMatcher(s, threshold=0.37, margin=0.06)
        assert matcher.person_count == 2
        assert matcher.embedding_version == "auraface-v1"

        match = matcher.match(alice)
        assert match.person_id == "alice"
        assert match.runner_up_id == "bob"
        s.close()


def test_matcher_dibangun_ulang_setelah_roster_berubah():
    with tempfile.TemporaryDirectory() as tmp:
        s = store(tmp)
        s.add_reference("alice", unit(1), JPEG, quality=0.9)
        s.add_reference("bob", unit(2), JPEG, quality=0.9)
        matcher = MatrixMatcher(s)

        s.set_roster({"alice": 1})
        matcher.rebuild()

        assert matcher.person_count == 1
        s.close()


def test_stats_melaporkan_yang_basi():
    with tempfile.TemporaryDirectory() as tmp:
        s = store(tmp)
        s.add_reference("4471", unit(1), JPEG, quality=0.8)
        s.add_reference("4471", unit(2), JPEG, quality=0.8, embedding_version="v0")

        stats = s.stats()
        assert stats["persons"] == 1
        assert stats["references_total"] == 2
        assert stats["references_usable"] == 1
        assert stats["references_stale"] == 1
        assert stats["image_bytes"] == len(JPEG) * 2
        s.close()
