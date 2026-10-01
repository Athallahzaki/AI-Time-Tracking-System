"""Tes ketahanan koneksi gerbang engine (P2 + temuan handshake 28 Sep 2026).

Semua yang diuji di sini adalah kegagalan yang TIDAK memunculkan error di sisi
engine: engine tetap hidup, log tetap tenang, tetapi tidak ada backend yang bisa
tersambung lagi. Dashboard tampak mati dan tidak ada yang tahu kenapa.

- Klien yang tersambung tapi diam tidak boleh menahan handshake klien lain.
- Baris pertama yang rusak tidak boleh mematikan loop accept.
- Backend lama yang berhenti membaca (thread kirim tertahan di `sendall` sambil
  memegang kunci tulis) tidak boleh mengunci handshake backend baru.
- Backend yang berhenti membaca akhirnya diputus (batas waktu kirim).
"""

from __future__ import annotations

import json
import socket
import tempfile
import threading
import time
from pathlib import Path

from engine.api import EngineApi, Outbox

HELLO = {
    "type": "hello", "v": 1, "ts": "2026-09-19T00:00:00.000Z",
    "protocol_version": 1, "client": "test",
}
PAD = "x" * 4000


def _event(index: int, pad: str = ""):
    event = {"type": "track.heartbeat", "v": 1, "ts": "2026-09-19T00:00:00.000Z", "n": index}
    if pad:
        event["pad"] = pad
    return event


def _start(api: EngineApi, tmp: str) -> str:
    path = str(Path(tmp) / "engine.sock")
    api.listen(socket_path=path)
    threading.Thread(target=api.serve_forever, daemon=True).start()
    time.sleep(0.1)
    return path


def _connect(path: str, timeout: float = 3.0) -> socket.socket:
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.settimeout(timeout)
    connection.connect(path)
    return connection


def _hello(connection: socket.socket, last_seq: int = 0):
    """Kirim hello, kembalikan (reader, pesan pertama)."""
    reader = connection.makefile("r", encoding="utf-8")
    connection.sendall((json.dumps({**HELLO, "last_event_seq": last_seq}) + "\n").encode())
    return reader, json.loads(reader.readline())


def _wait(predicate, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def test_klien_diam_tidak_menahan_backend_berikutnya():
    with tempfile.TemporaryDirectory() as tmp:
        api = EngineApi(outbox=Outbox(), handshake_timeout=0.5)
        path = _start(api, tmp)
        try:
            diam = _connect(path)            # tersambung, tidak mengirim apa pun

            backend = _connect(path, timeout=3.0)
            _, first = _hello(backend)
            assert first["type"] == "hello_ack", "backend wajib dilayani walau ada klien diam"

            # Klien diam diputus engine setelah batas handshake.
            diam.settimeout(3.0)
            assert diam.recv(1) == b"", "klien yang tidak mengirim hello wajib diputus"
            backend.close()
            diam.close()
        finally:
            api.close()


def test_baris_pertama_rusak_tidak_mematikan_loop_accept():
    with tempfile.TemporaryDirectory() as tmp:
        api = EngineApi(outbox=Outbox())
        path = _start(api, tmp)
        try:
            for junk in (b"bukan json\n", b"[]\n", b'{"type":"hello","last_event_seq":"abc"}\n', b"\xff\xfe\n"):
                liar = _connect(path)
                liar.sendall(junk)
                liar.settimeout(3.0)
                try:
                    liar.recv(4096)
                except OSError:
                    pass
                liar.close()

            backend = _connect(path)
            _, first = _hello(backend)
            assert first["type"] == "hello_ack", "engine wajib tetap menerima setelah input liar"
            backend.close()
        finally:
            api.close()


def test_backend_lama_yang_macet_tidak_mengunci_handshake_baru():
    """Batas waktu kirim sengaja besar: yang diuji adalah urutan putus-lalu-kunci,
    bukan timeout."""
    with tempfile.TemporaryDirectory() as tmp:
        api = EngineApi(outbox=Outbox(), send_timeout=60.0)
        path = _start(api, tmp)
        try:
            lama = _connect(path)
            _, first = _hello(lama)
            assert first["type"] == "hello_ack"

            # Backend lama berhenti membaca; ±8 MB event memenuhi buffer socket
            # sehingga thread kirim tertahan di sendall sambil memegang kunci tulis.
            for index in range(2000):
                api.emit_event(_event(index, PAD))
            time.sleep(0.5)

            baru = _connect(path, timeout=3.0)
            reader, first = _hello(baru, last_seq=0)
            assert first["type"] == "hello_ack", "handshake baru tidak boleh menunggu koneksi lama"

            # Dan backend baru benar-benar menerima event dari awal (replay).
            seqs = []
            while len(seqs) < 5:
                message = json.loads(reader.readline())
                if "seq" in message:
                    seqs.append(message["seq"])
            assert seqs == [1, 2, 3, 4, 5]
            baru.close()
            lama.close()
        finally:
            api.close()


def test_backend_yang_berhenti_membaca_diputus_oleh_batas_kirim():
    with tempfile.TemporaryDirectory() as tmp:
        api = EngineApi(outbox=Outbox(), send_timeout=0.5)
        path = _start(api, tmp)
        try:
            lama = _connect(path)
            _, first = _hello(lama)
            assert first["type"] == "hello_ack"
            for index in range(2000):
                api.emit_event(_event(index, PAD))

            assert _wait(lambda: api.metrics["connected"] == 0.0, timeout=5.0), (
                "backend yang tidak membaca wajib diputus, bukan ditunggu selamanya"
            )
            # Event tidak hilang: masih di outbox untuk diputar ulang.
            assert api.metrics["outbox_depth"] == 2000.0
            lama.close()
        finally:
            api.close()


def test_backend_lambat_yang_masih_membaca_tidak_diputus():
    """Batas kirim bukan batas baca: backend yang diam lama (tidak ada ACK,
    tidak ada kontrol) tetapi masih menerima tetap tersambung."""
    with tempfile.TemporaryDirectory() as tmp:
        api = EngineApi(outbox=Outbox(), send_timeout=0.3)
        path = _start(api, tmp)
        try:
            backend = _connect(path, timeout=5.0)
            reader, first = _hello(backend)
            assert first["type"] == "hello_ack"
            time.sleep(1.0)                          # diam > batas kirim
            api.emit_event(_event(1))
            message = json.loads(reader.readline())
            assert message["seq"] == 1
            assert api.metrics["connected"] == 1.0
            backend.close()
        finally:
            api.close()


def test_keepalive_terpasang_di_koneksi_tcp():
    api = EngineApi(outbox=Outbox())
    api.listen(tcp=("127.0.0.1", 0))
    port = api._server.getsockname()[1]
    threading.Thread(target=api.serve_forever, daemon=True).start()
    try:
        backend = socket.create_connection(("127.0.0.1", port), timeout=3.0)
        _, first = _hello(backend)
        assert first["type"] == "hello_ack"
        assert _wait(lambda: api._connection is not None, timeout=2.0)
        assert api._connection.getsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE) == 1
        backend.close()
    finally:
        api.close()
