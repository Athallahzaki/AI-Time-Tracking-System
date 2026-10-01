"""Tes perubahan protokol fase 1 (dibekukan 1 Okt 2026, dokumen 07 §1.4).

Semua perubahan bersifat TAMBAHAN: protocol_version tetap 1, dan pesan v1 lama
harus tetap lolos. Dua tes pertama menjaga janji itu; sisanya, seperti
test_contract.py, terutama memastikan pesan yang salah benar-benar ditolak.
"""

from __future__ import annotations

import pytest

from contracts import handshake_auth as auth
from contracts.validator import SchemaValidator
from contracts.validator.conformance import POLICY_FIELD_PATTERNS

TS = "2026-10-01T03:00:00.000Z"
NONCE_A = "a" * 64
NONCE_B = "b" * 64
KEY = "0123456789abcdef0123456789abcdef"


@pytest.fixture(scope="module")
def validator() -> SchemaValidator:
    return SchemaValidator()


def ok(validator, message, channel=None):
    issues = validator.validate_message(message, expected_channel=channel)
    assert issues == [], "\n".join(str(i) for i in issues)


def rejected(validator, message):
    assert validator.validate_message(message), f"seharusnya ditolak: {message}"


def hello(**extra):
    return {"type": "hello", "v": 1, "ts": TS, "protocol_version": 1,
            "client": "backend", "last_event_seq": 0, **extra}


def health(**extra):
    return {"type": "engine.health", "v": 1, "ts": TS, "seq": 7, "models_loaded": True,
            "queue_depth": 0, "drop_rate": 0.0, "cameras": {"cam01": "online"}, **extra}


# --------------------------------------------------------------------------
# janji kompatibilitas
# --------------------------------------------------------------------------


def test_tipe_fase_1_dikenal_validator(validator):
    assert {
        "auth_challenge", "enroll_from_track", "forget_person", "forget_result",
        "camera.recovered",
    } <= set(validator.known_types)


def test_pesan_v1_lama_tetap_lolos(validator):
    """Backend dan engine lama tidak boleh mendadak melanggar kontrak."""
    ok(validator, hello())
    ok(validator, health())
    ok(validator, {"type": "ack", "v": 1, "ts": TS, "in_reply_to": "set_cameras", "accepted": True})
    ok(validator, {"type": "camera.degraded", "v": 1, "ts": TS, "seq": 3,
                   "camera_id": "cam01", "reason": "lag"})


def test_bentuk_peta_status_kamera_dibekukan(validator):
    """Dokumen 07 menulis "engine.health.cameras diperluas per kamera". Mengubah
    nilai peta itu jadi objek mematahkan backend lama; angka per kamera wajib
    lewat camera_metrics."""
    rejected(validator, health(cameras={"cam01": {"status": "online", "lag_seconds": 0.3}}))


# --------------------------------------------------------------------------
# autentikasi handshake
# --------------------------------------------------------------------------


def test_auth_challenge_dan_hello_beraut_lolos(validator):
    ok(validator, {"type": "auth_challenge", "v": 1, "ts": TS, "nonce": NONCE_A,
                   "algorithm": "hmac-sha256"}, channel="control")
    mac = auth.hello_mac(KEY, NONCE_A, NONCE_B, "backend", 0)
    ok(validator, hello(auth={"client_nonce": NONCE_B, "mac": mac}))
    ok(validator, {"type": "hello_ack", "v": 1, "ts": TS, "protocol_version": 1,
                   "engine_version": "0.1.0", "oldest_available_seq": 0,
                   "models": {"detector": "d", "embedder": "e", "embedding_version": "x"},
                   "auth": {"mac": auth.hello_ack_mac(KEY, NONCE_A, NONCE_B)}})


@pytest.mark.parametrize("bad", [
    {"client_nonce": NONCE_B},                             # tanpa mac
    {"client_nonce": NONCE_B, "mac": "A" * 64},            # hex huruf besar
    {"client_nonce": "b" * 63, "mac": "c" * 64},           # nonce kependekan
    {"client_nonce": NONCE_B, "mac": "rahasia"},           # bukan hex
])
def test_auth_hello_cacat_ditolak(validator, bad):
    rejected(validator, hello(auth=bad))


def test_challenge_algoritma_lain_ditolak(validator):
    """Tidak ada negosiasi algoritma: celah downgrade klasik."""
    rejected(validator, {"type": "auth_challenge", "v": 1, "ts": TS, "nonce": NONCE_A,
                         "algorithm": "hmac-md5"})


def test_vektor_uji_hmac_beku():
    """Vektor ini kontrak lintas bahasa: kalau backend ditulis ulang di bahasa
    lain, hasilnya wajib persis sama. Mengubah format pesan kanonik = mengubah
    angka ini = perubahan yang memutus kompatibilitas."""
    assert auth.hello_mac(KEY, NONCE_A, NONCE_B, "backend", 42) == (
        "e74fb232a2dfd27cb0aa5d863926d2f78354c8abcfa0c3e0eef0f53b42bd019e"
    )
    assert auth.hello_ack_mac(KEY, NONCE_A, NONCE_B) == (
        "57fc1823a14a73793412396fb7c73ae02f69b6187f3010f865e74dffef265778"
    )


def test_mac_terikat_ke_isi_hello():
    base = auth.hello_mac(KEY, NONCE_A, NONCE_B, "backend", 42)
    assert auth.verify(base, auth.hello_mac(KEY, NONCE_A, NONCE_B, "backend", 42))
    for changed in (
        auth.hello_mac(KEY, NONCE_A, NONCE_B, "backend", 0),          # replay diminta ulang
        auth.hello_mac(KEY, NONCE_A, NONCE_B, "laptop", 42),
        auth.hello_mac(KEY, "c" * 64, NONCE_B, "backend", 42),         # challenge lain
        auth.hello_mac(KEY.upper(), NONCE_A, NONCE_B, "backend", 42),  # kunci lain
    ):
        assert not auth.verify(base, changed)


def test_mac_hello_tidak_bisa_dipantulkan_sebagai_bukti_engine():
    assert auth.hello_ack_mac(KEY, NONCE_A, NONCE_B) != auth.hello_mac(KEY, NONCE_A, NONCE_B, "", 0)


def test_kunci_pendek_dan_nonce_cacat_ditolak_keras():
    with pytest.raises(ValueError, match="terlalu pendek"):
        auth.hello_mac("rahasia", NONCE_A, NONCE_B, "backend", 0)
    with pytest.raises(ValueError, match="hex"):
        auth.hello_mac(KEY, "A" * 64, NONCE_B, "backend", 0)
    assert not auth.verify(auth.hello_ack_mac(KEY, NONCE_A, NONCE_B), None)


def test_nonce_baru_sesuai_skema_dan_tidak_berulang(validator):
    nonces = {auth.new_nonce() for _ in range(100)}
    assert len(nonces) == 100
    ok(validator, {"type": "auth_challenge", "v": 1, "ts": TS, "nonce": nonces.pop(),
                   "algorithm": "hmac-sha256"})


# --------------------------------------------------------------------------
# ack dua arah
# --------------------------------------------------------------------------


def test_ack_event_dari_backend_tercantum_di_skema(validator):
    """Sebelum fase 1, ACK yang dikirim backend tidak ada di skema sama sekali."""
    ok(validator, {"type": "ack", "v": 1, "ts": TS, "through_seq": 120}, channel="control")


@pytest.mark.parametrize("bad", [
    {"type": "ack", "v": 1, "ts": TS},                                        # kosong
    {"type": "ack", "v": 1, "ts": TS, "through_seq": 5, "accepted": True},    # campuran
    {"type": "ack", "v": 1, "through_seq": 5},                                # bentuk lama tanpa ts
    {"type": "ack", "v": 1, "ts": TS, "through_seq": -1},
])
def test_ack_cacat_ditolak(validator, bad):
    rejected(validator, bad)


# --------------------------------------------------------------------------
# health, degraded, recovered
# --------------------------------------------------------------------------


def test_camera_metrics_lolos_dan_angka_mustahil_ditolak(validator):
    ok(validator, health(
        camera_metrics={"cam01": {"lag_seconds": 0.4, "effective_fps": 11.8,
                                  "frames_dropped_stale": 3, "clock_drift_seconds": -0.2}},
        outbox_depth=12, disk_free_mb=20480.0,
    ))
    rejected(validator, health(camera_metrics={"cam01": {"lag_seconds": -1}}))
    rejected(validator, health(camera_metrics={"cam01": {"frames_dropped_stale": 1.5}}))
    rejected(validator, health(outbox_depth=-3))


def test_rentang_degraded_dibuka_dan_ditutup(validator):
    ok(validator, {"type": "camera.degraded", "v": 1, "ts": TS, "seq": 3, "camera_id": "cam01",
                   "reason": "gambar tidak berubah 30 dtk", "kind": "frozen_frame",
                   "since_at": "2026-10-01T02:59:30.000Z"}, channel="events")
    ok(validator, {"type": "camera.recovered", "v": 1, "ts": TS, "seq": 4, "camera_id": "cam01",
                   "kind": "frozen_frame", "since_at": "2026-10-01T02:59:30.000Z",
                   "until_at": TS}, channel="events")
    rejected(validator, {"type": "camera.recovered", "v": 1, "ts": TS, "seq": 4,
                         "camera_id": "cam01"})                     # tanpa until_at
    rejected(validator, {"type": "camera.degraded", "v": 1, "ts": TS, "seq": 3, "camera_id": "cam01",
                         "reason": "lag", "since_at": "2026-10-01 02:59:30"})  # bukan RFC3339 Z


def test_nama_field_baru_tidak_berbau_kebijakan():
    """Conformance menolak field berbau aturan kantor di kanal events."""
    for name in ("camera_metrics", "lag_seconds", "effective_fps", "frames_dropped_stale",
                 "clock_drift_seconds", "outbox_depth", "disk_free_mb", "kind", "since_at",
                 "until_at"):
        assert not any(p.search(name) for p in POLICY_FIELD_PATTERNS), name


# --------------------------------------------------------------------------
# enroll_from_track, forget_person
# --------------------------------------------------------------------------


def test_enroll_from_track(validator):
    message = {"type": "enroll_from_track", "v": 1, "ts": TS, "request_id": "r-9",
               "person_id": "emp_017", "enrollment_version": 3, "track_uuid": "tr_cam04_77"}
    ok(validator, message, channel="control")
    rejected(validator, {k: v for k, v in message.items() if k != "track_uuid"})
    rejected(validator, dict(message, track_uuid="iv_cam04_77"))   # interval_id bukan track
    ok(validator, {"type": "enroll_result", "v": 1, "ts": TS, "request_id": "r-9",
                   "accepted": False, "reason": "track_unavailable", "images": []})


def test_forget_person_dijawab_bukti(validator):
    ok(validator, {"type": "forget_person", "v": 1, "ts": TS, "request_id": "f-1",
                   "person_id": "emp_017"}, channel="control")
    ok(validator, {"type": "forget_result", "v": 1, "ts": TS, "request_id": "f-1",
                   "person_id": "emp_017", "removed_references": 0})
    rejected(validator, {"type": "forget_result", "v": 1, "ts": TS, "request_id": "f-1",
                         "person_id": "emp_017"})                   # tanpa jumlah
    rejected(validator, {"type": "forget_person", "v": 1, "ts": TS, "request_id": "f-1",
                         "person_id": "emp 017"})                   # pola person_id
