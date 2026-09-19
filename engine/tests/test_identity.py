"""Tes lapisan identitas.

Setiap tes di sini dinamai menurut bug yang dicegahnya, bukan menurut metode
yang dipanggilnya. Semua bug itu punya sifat yang sama dan itulah alasan
mereka berbahaya: **sistem mencatat data yang salah tanpa memunculkan satu pun
error.** Log bersih, dashboard hidup, dan orang yang salah tercatat hadir.

Yang diuji bukan "apakah identitas yang benar dikenali" — itu bagian mudahnya.
Yang diuji adalah apakah identitas yang salah benar-benar DITOLAK.
"""

from __future__ import annotations

import numpy as np
import pytest

from engine.identity import (
    Evidence,
    EvidenceWindow,
    IdentityArbiter,
    IdentityState,
    InMemoryReferenceStore,
    MatrixMatcher,
    Outcome,
    VersionMismatch,
)

DIM = 64


def unit(seed: int) -> np.ndarray:
    vector = np.random.default_rng(seed).normal(size=DIM).astype(np.float32)
    return vector / np.linalg.norm(vector)


def blend(a: np.ndarray, b: np.ndarray, t: float) -> np.ndarray:
    """Vektor antara `a` dan `b`; t=0 berarti persis `a`."""
    mixed = (1.0 - t) * a + t * b
    return (mixed / np.linalg.norm(mixed)).astype(np.float32)


ALICE = unit(1)
BOB = unit(2)
# Sengaja dibuat mirip Alice: inilah kasus yang uji margin ada untuk menangkap.
MIRIP_ALICE = blend(ALICE, unit(3), 0.25)


def build(references=None, **kwargs):
    if references is None:
        references = {"alice": [ALICE], "bob": [BOB]}
    store = InMemoryReferenceStore(references)
    matcher = MatrixMatcher(store, threshold=0.37, margin=0.06)
    defaults = dict(min_evidence=3, min_spread_seconds=0.5, window=5)
    defaults.update(kwargs)
    return store, matcher, IdentityArbiter(matcher, **defaults)


def feed(arbiter, track, camera, vector, times, quality=0.9, version="test-v1"):
    """Suapi beberapa bukti pada pts yang ditentukan. Kembalikan keputusan terakhir."""
    decision = None
    for pts in times:
        decision = arbiter.observe(track, camera, Evidence(vector, pts, quality, version))
    return decision


# --------------------------------------------------------------------------
# §9.1 — satu match tunggal membuka sesi
# --------------------------------------------------------------------------


def test_satu_bukti_tunggal_tidak_membuka_identitas():
    """Implementasi lama menyetel CONFIRMED pada match pertama, dan hilirnya
    menyalin identitas itu ke sesi kehadiran. Satu frame cukup untuk seseorang
    tercatat hadir sepanjang hari."""
    _, _, arbiter = build()
    decision = arbiter.observe("tr_1", "r1", Evidence(ALICE, 0.0, 0.9, "test-v1"))

    assert decision.outcome is Outcome.NOTHING
    assert decision.identity.person_id is None
    assert decision.identity.state is IdentityState.PROVISIONAL
    assert decision.reason == "not_enough_evidence"


def test_konfirmasi_butuh_sebaran_waktu_bukan_hanya_jumlah():
    """Lima bukti dari satu momen yang sama secara statistik adalah satu bukti
    yang disalin lima kali: pose sama, blur sama, error berkorelasi penuh."""
    _, _, arbiter = build()

    rapat = feed(arbiter, "tr_1", "r1", ALICE, [0.0, 0.1, 0.2])
    assert rapat.identity.person_id is None, "tiga bukti dalam 0,2 detik tidak boleh cukup"

    tersebar = feed(arbiter, "tr_2", "r1", ALICE, [0.0, 0.4, 0.9])
    assert tersebar.outcome is Outcome.IDENTIFIED
    assert tersebar.identity.person_id == "alice"
    assert tersebar.identity.state is IdentityState.CONFIRMED


# --------------------------------------------------------------------------
# §9.2 — tidak ada uji margin
# --------------------------------------------------------------------------


def test_orang_yang_mirip_dua_karyawan_tidak_diklaim_siapa_pun():
    """Threshold cuma bertanya "cukup mirip?". Tanpa pertanyaan kedua, orang
    asing yang menyerupai dua karyawan diberikan ke salah satunya dengan
    percaya diri."""
    kembar = blend(ALICE, BOB, 0.5)
    _, matcher, arbiter = build({"alice": [ALICE], "bob": [BOB], "mirip": [MIRIP_ALICE]})

    match = matcher.match(kembar)
    assert match.person_id is None
    assert match.rejected_because in {"margin_too_narrow", "below_threshold"}

    decision = feed(arbiter, "tr_1", "r1", kembar, [0.0, 0.4, 0.9])
    assert decision.identity.person_id is None


def test_margin_dihitung_antar_orang_bukan_antar_foto():
    """Kalau `second_best` diambil per vektor referensi, kandidat kedua hampir
    selalu foto lain milik orang yang sama, margin-nya mendekati nol, dan
    SELURUH roster ditolak. Foto kedua bukan saingan; ia bukti tambahan."""
    lima_foto_alice = [ALICE, blend(ALICE, unit(10), 0.05), blend(ALICE, unit(11), 0.07),
                       blend(ALICE, unit(12), 0.04), blend(ALICE, unit(13), 0.06)]
    _, matcher, _ = build({"alice": lima_foto_alice, "bob": [BOB]})

    match = matcher.match(ALICE)
    assert match.person_id == "alice"
    assert match.runner_up_id == "bob", "kandidat kedua wajib orang lain, bukan foto lain"
    assert match.margin > 0.06


def test_roster_tidak_seimbang_tidak_menguntungkan_yang_fotonya_banyak():
    """Dengan pemeringkatan per vektor, karyawan berfoto lima punya lima undian
    melawan karyawan berfoto satu."""
    _, matcher, _ = build({
        "alice": [ALICE],
        "bob": [BOB] + [blend(BOB, unit(20 + i), 0.15) for i in range(6)],
    })
    match = matcher.match(ALICE)
    assert match.person_id == "alice"


# --------------------------------------------------------------------------
# §9.4 — verifikasi ulang yang tidak setuju membajak identitas
# --------------------------------------------------------------------------


def test_satu_frame_buruk_tidak_membajak_track_yang_stabil():
    """Perilaku lama: `update_with_match` menukar identitas dan mereset
    penghitung begitu match berbeda datang, lalu tetap menyetel CONFIRMED."""
    _, _, arbiter = build()
    feed(arbiter, "tr_1", "r1", ALICE, [0.0, 0.4, 0.9])

    decision = arbiter.observe("tr_1", "r1", Evidence(BOB, 1.2, 0.9, "test-v1"))

    assert decision.outcome is Outcome.NOTHING
    assert decision.identity.person_id == "alice", "satu frame nyasar tidak boleh merebut track"
    assert decision.identity.disagreements == 1


def test_tiga_ketidaksetujuan_berturut_turut_melepas_klaim():
    _, _, arbiter = build(disagreements_to_release=3)
    feed(arbiter, "tr_1", "r1", ALICE, [0.0, 0.4, 0.9])

    for pts in (1.2, 1.6, 2.0):
        decision = arbiter.observe("tr_1", "r1", Evidence(BOB, pts, 0.9, "test-v1"))

    assert decision.outcome is Outcome.IDENTITY_RELEASED
    assert decision.from_person_id == "alice"
    assert decision.reason == "sustained_disagreement"
    # Dilepas, BUKAN ditukar: mengganti nama begitu saja akan membuat backend
    # mencatat kehadiran orang kedua yang belum pernah benar-benar terkonfirmasi.
    assert decision.identity.person_id is None


def test_ketidaksetujuan_ke_orang_berbeda_beda_tidak_menumpuk():
    """Tiga suara menentang ke tiga orang berbeda bukan bukti bahwa klaim
    sekarang salah; itu bukti bahwa pengenalannya sedang berisik."""
    carol = unit(7)
    _, _, arbiter = build({"alice": [ALICE], "bob": [BOB], "carol": [carol]},
                          disagreements_to_release=3)
    feed(arbiter, "tr_1", "r1", ALICE, [0.0, 0.4, 0.9])

    arbiter.observe("tr_1", "r1", Evidence(BOB, 1.2, 0.9, "test-v1"))
    decision = arbiter.observe("tr_1", "r1", Evidence(carol, 1.6, 0.9, "test-v1"))

    assert decision.identity.person_id == "alice"
    assert decision.identity.disagreements == 1


def test_gagal_mencocokkan_bukan_suara_menentang():
    """Punggung orang tidak boleh mencabut identitasnya sendiri. Ketiadaan
    bukti bukan bukti yang berlawanan."""
    _, _, arbiter = build(disagreements_to_release=3)
    feed(arbiter, "tr_1", "r1", ALICE, [0.0, 0.4, 0.9])

    asing = unit(99)
    for pts in (1.2, 1.6, 2.0, 2.4):
        decision = arbiter.observe("tr_1", "r1", Evidence(asing, pts, 0.3, "test-v1"))

    assert decision.identity.person_id == "alice"
    assert decision.identity.disagreements == 0


# --------------------------------------------------------------------------
# §9.5 — tidak ada dedup identitas antar track
# --------------------------------------------------------------------------


def test_dua_track_di_satu_kamera_tidak_boleh_mengklaim_orang_yang_sama():
    _, _, arbiter = build()
    feed(arbiter, "tr_1", "r1", blend(ALICE, unit(30), 0.12), [0.0, 0.4, 0.9])
    assert arbiter.identity_of("tr_1").person_id == "alice"

    lebih_mirip = feed(arbiter, "tr_2", "r1", ALICE, [1.0, 1.4, 1.9])

    assert lebih_mirip.identity.person_id == "alice"
    assert arbiter.identity_of("tr_1").person_id is None, "yang similarity-nya lebih rendah melepas klaim"


def test_klaim_dengan_similarity_lebih_rendah_ditolak_bukan_merebut():
    _, _, arbiter = build()
    feed(arbiter, "tr_1", "r1", ALICE, [0.0, 0.4, 0.9])

    lebih_lemah = feed(arbiter, "tr_2", "r1", blend(ALICE, unit(31), 0.15), [1.0, 1.4, 1.9])

    assert lebih_lemah.reason == "dedup_lost_claim"
    assert lebih_lemah.identity.person_id is None
    assert arbiter.identity_of("tr_1").person_id == "alice"


def test_dedup_tidak_berlaku_lintas_kamera():
    """Orang yang sama terlihat di dua kamera adalah pertanyaan topologi
    (§5.4) dan penyambungan sesi — milik backend. Bukan tabrakan klaim."""
    _, _, arbiter = build()
    feed(arbiter, "tr_1", "r1", ALICE, [0.0, 0.4, 0.9])
    feed(arbiter, "tr_2", "r2", ALICE, [1.0, 1.4, 1.9])

    assert arbiter.identity_of("tr_1").person_id == "alice"
    assert arbiter.identity_of("tr_2").person_id == "alice"


# --------------------------------------------------------------------------
# HELD: identitas tanpa wajah
# --------------------------------------------------------------------------


def test_identitas_berpindah_ke_held_lalu_expired_seiring_waktu():
    _, _, arbiter = build(held_after_seconds=3.0, ttl_seconds=60.0)
    feed(arbiter, "tr_1", "r1", ALICE, [0.0, 0.4, 0.9])
    puncak = arbiter.identity_of("tr_1").confidence

    arbiter.tick(5.0)
    identity = arbiter.identity_of("tr_1")
    assert identity.state is IdentityState.HELD
    assert identity.person_id == "alice", "identitas bertahan saat orang membelakangi kamera"
    assert identity.identity_source == "tracking"
    assert identity.confidence < puncak

    arbiter.tick(120.0)
    assert arbiter.identity_of("tr_1").state is IdentityState.EXPIRED


def test_identity_source_membedakan_wajah_dari_tracker():
    """Backend perlu tahu bedanya identitas yang baru diverifikasi dari wajah
    dan identitas yang sedang dipegang tracker: keandalannya berbeda."""
    _, _, arbiter = build(held_after_seconds=3.0)
    feed(arbiter, "tr_1", "r1", ALICE, [0.0, 0.4, 0.9])
    assert arbiter.identity_of("tr_1").identity_source == "face"

    arbiter.tick(10.0)
    assert arbiter.identity_of("tr_1").identity_source == "tracking"

    arbiter.observe("tr_1", "r1", Evidence(ALICE, 10.5, 0.9, "test-v1"))
    assert arbiter.identity_of("tr_1").identity_source == "face"


def test_penyambungan_memindahkan_klaim_sebagai_held():
    """Identitas yang pindah lewat `track.resumed` tidak berasal dari wajah
    yang baru dibaca, jadi ia tidak boleh masuk sebagai CONFIRMED."""
    _, _, arbiter = build()
    feed(arbiter, "tr_1", "r1", ALICE, [0.0, 0.4, 0.9])

    arbiter.open_track("tr_2", "r1")
    adopted = arbiter.adopt("tr_2", "r1", "tr_1")

    assert adopted.person_id == "alice"
    assert adopted.state is IdentityState.HELD
    assert arbiter.identity_of("tr_1").person_id is None


# --------------------------------------------------------------------------
# versi model dan fusi
# --------------------------------------------------------------------------


def test_versi_embedding_tidak_cocok_ditolak_bukan_dibandingkan():
    """Cosine antara vektor dari dua model bukan angka yang salah — ia angka
    tanpa arti. Tanpa pemeriksaan ini, mengganti embedder menjatuhkan akurasi
    ke tingkat acak tanpa satu pun error."""
    _, matcher, arbiter = build()
    with pytest.raises(VersionMismatch):
        matcher.match(ALICE, query_version="model-lain-v2")
    with pytest.raises(VersionMismatch):
        arbiter.observe("tr_1", "r1", Evidence(ALICE, 0.0, 0.9, "model-lain-v2"))


def test_fusi_menormalisasi_ulang():
    """Rata-rata vektor satuan tidak lagi berada di bola satuan. Tanpa
    normalisasi ulang, skornya mengecil sebanding dengan ketidaksepakatan
    internal bukti — yang terlihat seperti kemiripan rendah."""
    window = EvidenceWindow(window=5, min_evidence=3, min_spread_seconds=0.5)
    for index, pts in enumerate((0.0, 0.4, 0.9)):
        window.add(Evidence(blend(ALICE, unit(40 + index), 0.2), pts, 0.5 + 0.2 * index))

    fused = window.fused()
    assert abs(float(np.linalg.norm(fused)) - 1.0) < 1e-5
    assert window.is_confirmable


def test_bukti_bermutu_tinggi_menarik_hasil_fusi():
    window = EvidenceWindow(window=5, min_evidence=2, min_spread_seconds=0.1)
    window.add(Evidence(ALICE, 0.0, 0.95))
    window.add(Evidence(BOB, 0.5, 0.05))

    fused = window.fused()
    assert float(fused @ ALICE) > float(fused @ BOB)


def test_roster_kosong_tidak_meledak():
    _, _, arbiter = build({})
    decision = arbiter.observe("tr_1", "r1", Evidence(ALICE, 0.0, 0.9, "test-v1"))
    assert decision.identity.person_id is None
    assert decision.reason == "empty_roster"


def test_menutup_track_melepas_klaimnya():
    """Kalau tidak, karyawan yang keluar ruangan memblokir identitasnya sendiri
    saat ia masuk lagi."""
    _, _, arbiter = build()
    feed(arbiter, "tr_1", "r1", ALICE, [0.0, 0.4, 0.9])
    arbiter.close_track("tr_1")

    kembali = feed(arbiter, "tr_2", "r1", ALICE, [10.0, 10.4, 10.9])
    assert kembali.outcome is Outcome.IDENTIFIED
    assert kembali.identity.person_id == "alice"
