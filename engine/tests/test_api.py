"""Tes gerbang engine: outbox, replay, pembentukan pesan, dan sifat non-blok.

Yang diuji di sini hampir semuanya tentang kegagalan yang tidak memunculkan
error: nomor urut yang dipakai ulang setelah restart, event yang hilang karena
dikirim sebelum disimpan, lubang data yang lewat tanpa diumumkan, dan frame
loop yang berhenti karena backend lambat.
"""

from __future__ import annotations

import json
import socket
import tempfile
import threading
import time
from pathlib import Path

import pytest

from contracts.validator import SchemaValidator
from engine.api import (
    EngineApi,
    Outbox,
    ProtocolError,
    PtsClock,
    SqliteOutbox,
    camera_online,
    presence_interval,
    track_ended,
    track_identified,
    track_started,
    view_frame,
)

OFFSET = 1758240000.0


def clock(camera="r1", epoch=0):
    return PtsClock(camera_id=camera, stream_epoch=epoch, offset=OFFSET)


def dummy_event(index: int = 0):
    return {"type": "track.heartbeat", "v": 1, "ts": "2026-09-19T00:00:00.000Z", "n": index}


# --------------------------------------------------------------------------
# outbox durabel
# --------------------------------------------------------------------------


def test_nomor_urut_bertahan_melintasi_restart_engine():
    """Kalau engine restart lalu mulai lagi dari seq 1, backend yang menyimpan
    last_event_seq = 10432 akan membuang seluruh aliran berikutnya sebagai
    "sudah pernah dilihat" — diam-diam, dan yang hilang adalah kehadiran orang
    sepanjang sisa hari itu."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "outbox.db"

        first = SqliteOutbox(path)
        for index in range(5):
            first.append(dummy_event(index))
        assert first.latest_seq == 5
        first.close()

        second = SqliteOutbox(path)
        stored = second.append(dummy_event(99))
        assert stored["seq"] == 6, "penomoran wajib lanjut, bukan mulai ulang"
        second.close()


def test_nomor_urut_tidak_dipakai_ulang_walau_outbox_dikosongkan():
    """MAX(seq) mengembalikan NULL setelah seluruh isi dipangkas. Tanpa
    high-water mark tersimpan, penomoran akan mulai lagi dari 1."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "outbox.db"

        first = SqliteOutbox(path)
        for index in range(5):
            first.append(dummy_event(index))
        first.ack(through_seq=5)
        assert len(first) == 0
        first.close()

        second = SqliteOutbox(path)
        assert second.append(dummy_event(0))["seq"] == 6
        second.close()


def test_replay_dari_last_event_seq_menghasilkan_aliran_yang_sama():
    outbox = Outbox()
    stored = [outbox.append(dummy_event(index)) for index in range(10)]

    replayed = outbox.since(6)
    assert [message["seq"] for message in replayed] == [7, 8, 9, 10]
    assert replayed == stored[6:]


def test_lubang_data_diumumkan_saat_outbox_tidak_cukup_jauh_ke_belakang():
    outbox = Outbox()
    for index in range(10):
        outbox.append(dummy_event(index))
    outbox.ack(through_seq=5)

    gap = outbox.gap_for(last_event_seq=2)
    assert gap is not None
    assert gap["from_seq"] == 2 and gap["to_seq"] == 6

    assert outbox.gap_for(last_event_seq=5) is None, "bersambung, bukan lubang"


def test_backend_baru_tidak_dianggap_punya_lubang():
    """last_event_seq = 0 berarti backend baru dan tidak meminta apa-apa."""
    outbox = Outbox()
    for index in range(3):
        outbox.append(dummy_event(index))
    outbox.ack(through_seq=3)

    assert outbox.gap_for(last_event_seq=0) is None


def test_pemangkasan_hanya_setelah_ack():
    outbox = Outbox()
    for index in range(4):
        outbox.append(dummy_event(index))

    assert len(outbox) == 4
    assert outbox.ack(through_seq=2) == 2
    assert outbox.oldest_available_seq == 3


# --------------------------------------------------------------------------
# pembentukan pesan
# --------------------------------------------------------------------------


def test_pesan_yang_dibentuk_lolos_skema_kontrak():
    """Kalau ini gagal, engine asli akan memancarkan sesuatu yang engine palsu
    tidak pernah memancarkan, dan ketidakcocokannya baru ketahuan di M3."""
    validator = SchemaValidator()
    c = clock()

    messages = [
        camera_online(c, fps=10.0),
        track_started(c, "tr_r1-t1", pts=12.0, zone="door"),
        track_identified(c, "tr_r1-t1", "4471", pts=14.4, track_started_pts=12.0,
                         similarity=0.91, margin=0.17, evidence_count=3),
        track_ended(c, "tr_r1-t1", pts=240.0, reason="left_frame", exit_zone="door"),
        presence_interval(c, "iv_r1-0001", "4471", start_pts=12.0, end_pts=240.0,
                          start_source="face", end_source="face",
                          start_zone="door", end_zone="door", end_reason="left_frame",
                          identity_confidence=0.91, evidence_count=4, track_uuid="tr_r1-t1"),
    ]

    for index, message in enumerate(messages, start=1):
        message["seq"] = index
        issues = validator.validate_message(message, expected_channel="events")
        assert issues == [], f"{message['type']}: {[str(i) for i in issues]}"

    frame = view_frame(c, pts=100.0, boxes=[{"track_uuid": "tr_r1-t1", "bbox": [0.1, 0.2, 0.3, 0.9]}])
    assert validator.validate_message(frame, expected_channel="view") == []


def test_track_identified_menolak_identifikasi_sebelum_track_lahir():
    with pytest.raises(ProtocolError):
        track_identified(clock(), "tr_1", "4471", pts=5.0, track_started_pts=9.0,
                         similarity=0.9, margin=0.1, evidence_count=3)


def test_track_ended_menolak_alasan_yang_tidak_dikenal():
    with pytest.raises(ProtocolError):
        track_ended(clock(), "tr_1", pts=10.0, reason="track_lost", exit_zone="door")


def test_interval_id_wajib_beda_ruang_nama_dari_track_uuid():
    with pytest.raises(ProtocolError):
        presence_interval(clock(), "tr_r1-t1", "4471", 0.0, 1.0, "face", "face",
                          "door", "door", "left_frame", 0.9, 3)


def test_bbox_piksel_ditolak_saat_dibentuk():
    """Engine melihat mainstream, browser menampilkan substream. Koordinat
    piksel akan meleset di resolusi yang berbeda."""
    with pytest.raises(ProtocolError):
        view_frame(clock(), pts=1.0, boxes=[{"track_uuid": "tr_1", "bbox": [310, 220, 440, 780]}])


def test_reconnect_menaikkan_epoch_dan_menetapkan_ulang_offset():
    awal = clock()
    baru = awal.reconnect(wallclock_now=OFFSET + 500.0)

    assert baru.stream_epoch == awal.stream_epoch + 1
    assert baru.offset > awal.offset
    # pts kembali ke nol, tapi jam dinding tidak ikut mundur.
    assert baru.at(0.0) > awal.at(400.0)


def test_pts_negatif_ditolak():
    with pytest.raises(ProtocolError):
        clock().at(-1.0)


# --------------------------------------------------------------------------
# sifat non-blok dan urutan simpan-lalu-kirim
# --------------------------------------------------------------------------


def test_event_disimpan_sebelum_dikirim():
    """Event yang terkirim tapi belum tersimpan akan hilang kalau engine mati
    sebelum sempat menulisnya — dan backend tidak akan memintanya lagi, karena
    ia sudah menerimanya."""
    api = EngineApi(outbox=Outbox())
    stored = api.emit_event(dummy_event(0))

    assert stored["seq"] == 1
    assert len(api._outbox) == 1, "sudah durabel meski belum ada backend yang tersambung"


def test_emit_tidak_memblok_saat_tidak_ada_backend():
    """Frame loop tidak boleh berhenti karena tidak ada yang mendengarkan."""
    api = EngineApi(outbox=Outbox(max_entries=10_000))

    started = time.monotonic()
    for index in range(2_000):
        api.emit_event(dummy_event(index))
        api.emit_view({"type": "view.frame", "v": 1, "ts": "x", "n": index})
    elapsed = time.monotonic() - started

    assert elapsed < 2.0, f"emit memblok: {elapsed:.2f}s"
    assert api.metrics["dropped_views"] > 0, "view wajib dibuang saat menumpuk"


def test_view_dibuang_tapi_event_tidak_pernah():
    api = EngineApi(outbox=Outbox(max_entries=10_000))
    for index in range(500):
        api.emit_event(dummy_event(index))
        api.emit_view({"type": "view.frame", "v": 1, "ts": "x", "n": index})

    assert len(api._outbox) == 500, "event domain tidak boleh hilang"
    assert api.metrics["dropped_views"] > 0


def test_view_yang_dibuang_adalah_yang_tertua():
    """Kotak dari posisi yang sudah ditinggalkan orangnya tidak lebih berguna
    daripada kotak dari posisinya sekarang."""
    api = EngineApi(outbox=Outbox())
    for index in range(300):
        api.emit_view({"type": "view.frame", "v": 1, "ts": "x", "n": index})

    tersisa = []
    while not api._views.empty():
        tersisa.append(api._views.get_nowait()["n"])

    assert max(tersisa) == 299, "frame terbaru wajib bertahan"


# --------------------------------------------------------------------------
# socket sungguhan
# --------------------------------------------------------------------------


def _client(path, last_seq=0, expect=6, timeout=8.0):
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.settimeout(timeout)
    connection.connect(path)
    stream = connection.makefile("r", encoding="utf-8")
    connection.sendall((json.dumps({
        "type": "hello", "v": 1, "ts": "2026-09-19T00:00:00.000Z",
        "protocol_version": 1, "client": "test", "last_event_seq": last_seq,
    }) + "\n").encode())

    received = []
    for line in stream:
        line = line.strip()
        if line:
            received.append(json.loads(line))
        if len(received) >= expect:
            break
    return connection, received


def test_jabat_tangan_replay_dan_lubang_lewat_socket():
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "engine.sock")
        api = EngineApi(outbox=Outbox())
        for index in range(5):
            api.emit_event(dummy_event(index))

        api.listen(socket_path=path)
        threading.Thread(target=api.serve_forever, daemon=True).start()
        time.sleep(0.2)

        try:
            connection, received = _client(path, last_seq=2, expect=4)
            kinds = [message["type"] for message in received]
            assert kinds[0] == "hello_ack"
            seqs = [m["seq"] for m in received if "seq" in m]
            assert seqs == [3, 4, 5], f"replay salah: {seqs}"
            connection.close()
        finally:
            api.close()


def test_hello_wajib_pesan_pertama():
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "engine.sock")
        api = EngineApi(outbox=Outbox())
        api.listen(socket_path=path)
        threading.Thread(target=api.serve_forever, daemon=True).start()
        time.sleep(0.2)

        try:
            connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            connection.settimeout(8.0)
            connection.connect(path)
            stream = connection.makefile("r", encoding="utf-8")
            connection.sendall(b'{"type":"set_cameras","v":1,"ts":"x","cameras":[]}\n')

            reply = json.loads(stream.readline())
            assert reply["type"] == "ack" and reply["accepted"] is False
            connection.close()
        finally:
            api.close()


def test_perintah_control_diteruskan_ke_penangan_dan_di_ack_segera():
    """Membuka RTSP bisa makan lima detik dan bisa gagal. Perintah di-ack saat
    diterima, hasilnya menyusul sebagai event."""
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "engine.sock")
        diterima = []

        api = EngineApi(outbox=Outbox())
        api.on_control("set_cameras", lambda message: diterima.append(message) or None)
        api.listen(socket_path=path)
        threading.Thread(target=api.serve_forever, daemon=True).start()
        time.sleep(0.2)

        try:
            connection, received = _client(path, expect=1)
            connection.sendall(b'{"type":"set_cameras","v":1,"ts":"x","cameras":[]}\n')

            stream = connection.makefile("r", encoding="utf-8")
            reply = json.loads(stream.readline())
            assert reply["type"] == "ack" and reply["accepted"] is True
            assert len(diterima) == 1
            connection.close()
        finally:
            api.close()
