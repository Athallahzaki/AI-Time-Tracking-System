"""Sisi engine dari kontrak fase 1: autentikasi handshake (P3), forget_person
(P14/E13), dan field kesehatan baru.

Yang paling penting di sini bukan bahwa klien sah bisa masuk, melainkan:
- klien tanpa kunci tidak bisa masuk dan TIDAK menendang backend sah (E3);
- data wajah yang "dihapus" benar-benar hilang dari berkas, bukan cuma
  ditandai halaman bebas yang masih bisa dibaca dengan hex editor.
"""

from __future__ import annotations

import json
import socket
import tempfile
import threading
import time
from pathlib import Path

import numpy as np
import pytest

from contracts import handshake_auth as auth
from contracts.validator import SchemaValidator
from engine.api import EngineApi, Outbox

KEY = "kunci-uji-0123456789abcdef-0123456789"


def _start(api: EngineApi, tmp: str) -> str:
    path = str(Path(tmp) / "engine.sock")
    api.listen(socket_path=path)
    threading.Thread(target=api.serve_forever, daemon=True).start()
    time.sleep(0.1)
    return path


def _open(path: str):
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.settimeout(3.0)
    connection.connect(path)
    return connection, connection.makefile("r", encoding="utf-8")


def _send(connection, message):
    connection.sendall((json.dumps(message) + "\n").encode())


def _hello(client="backend", last_event_seq=0, auth_block=None):
    message = {"type": "hello", "v": 1, "ts": "2026-10-01T00:00:00.000Z",
               "protocol_version": 1, "client": client, "last_event_seq": last_event_seq}
    if auth_block is not None:
        message["auth"] = auth_block
    return message


def _authenticated(path, key=KEY, client="backend"):
    """Handshake sah lengkap; kembalikan (koneksi, reader, challenge, hello_ack)."""
    connection, reader = _open(path)
    challenge = json.loads(reader.readline())
    client_nonce = auth.new_nonce()
    mac = auth.hello_mac(key, challenge["nonce"], client_nonce, client, 0)
    _send(connection, _hello(client, 0, {"client_nonce": client_nonce, "mac": mac}))
    reply = json.loads(reader.readline())
    return connection, reader, challenge, client_nonce, reply


# --------------------------------------------------------------------------
# autentikasi handshake
# --------------------------------------------------------------------------


def test_backend_dengan_kunci_masuk_dan_engine_membuktikan_diri():
    with tempfile.TemporaryDirectory() as tmp:
        api = EngineApi(outbox=Outbox(), auth_key=KEY)
        path = _start(api, tmp)
        try:
            connection, _, challenge, client_nonce, reply = _authenticated(path)
            validator = SchemaValidator()
            assert validator.validate_message(challenge, expected_channel="control") == []
            assert reply["type"] == "hello_ack", reply
            assert validator.validate_message(reply, expected_channel="control") == []
            expected = auth.hello_ack_mac(KEY, challenge["nonce"], client_nonce)
            assert auth.verify(expected, reply["auth"]["mac"]), "bukti balik engine salah"
            connection.close()
        finally:
            api.close()


@pytest.mark.parametrize("variant", ["tanpa_auth", "kunci_salah", "mac_untuk_challenge_lain", "nonce_cacat"])
def test_klien_tanpa_kunci_ditolak(variant):
    with tempfile.TemporaryDirectory() as tmp:
        api = EngineApi(outbox=Outbox(), auth_key=KEY)
        path = _start(api, tmp)
        try:
            connection, reader = _open(path)
            challenge = json.loads(reader.readline())
            nonce = auth.new_nonce()
            if variant == "tanpa_auth":
                block = None
            elif variant == "kunci_salah":
                block = {"client_nonce": nonce,
                         "mac": auth.hello_mac("kunci-lain-0123456789abcdef", challenge["nonce"], nonce, "backend", 0)}
            elif variant == "mac_untuk_challenge_lain":
                block = {"client_nonce": nonce,
                         "mac": auth.hello_mac(KEY, auth.new_nonce(), nonce, "backend", 0)}
            else:
                block = {"client_nonce": "XYZ", "mac": "0" * 64}
            _send(connection, _hello(auth_block=block))
            reply = json.loads(reader.readline())
            assert reply["type"] == "ack" and reply["accepted"] is False
            assert reply["reason"] == "auth_failed"
            assert connection.recv(1) == b"", "koneksi wajib ditutup setelah auth gagal"
            assert api.metrics["auth_failures"] == 1.0
            connection.close()
        finally:
            api.close()


def test_klien_liar_tidak_bisa_menendang_backend_sah():
    """E3: laptop pengembang yang menyambung ke engine produksi."""
    with tempfile.TemporaryDirectory() as tmp:
        api = EngineApi(outbox=Outbox(), auth_key=KEY)
        path = _start(api, tmp)
        try:
            sah, reader, *_ = _authenticated(path)
            api.emit_event({"type": "track.heartbeat", "v": 1, "ts": "2026-10-01T00:00:00.000Z", "n": 1})
            assert json.loads(reader.readline())["seq"] == 1

            liar, liar_reader = _open(path)
            json.loads(liar_reader.readline())
            _send(liar, _hello(client="laptop"))
            assert json.loads(liar_reader.readline())["reason"] == "auth_failed"
            liar.close()

            api.emit_event({"type": "track.heartbeat", "v": 1, "ts": "2026-10-01T00:00:00.000Z", "n": 2})
            assert json.loads(reader.readline())["seq"] == 2, "backend sah wajib tetap tersambung"
            assert api.metrics["connected"] == 1.0
            sah.close()
        finally:
            api.close()


def test_hello_tanpa_challenge_tetap_berlaku_bila_auth_mati():
    """Auth opsional: engine dan backend bisa diperbarui bergantian."""
    with tempfile.TemporaryDirectory() as tmp:
        api = EngineApi(outbox=Outbox())
        path = _start(api, tmp)
        try:
            connection, reader = _open(path)
            _send(connection, _hello())
            reply = json.loads(reader.readline())
            assert reply["type"] == "hello_ack" and "auth" not in reply
            connection.close()
        finally:
            api.close()


def test_kunci_pendek_menggagalkan_start():
    with pytest.raises(ValueError, match="terlalu pendek"):
        EngineApi(outbox=Outbox(), auth_key="rahasia")


def test_fake_engine_memakai_handshake_yang_sama():
    """Backend menguji klien auth-nya terhadap fake engine, tanpa GPU."""
    from engine.tools.fake_engine.server import FakeEngineServer

    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "fake.sock")
        server = FakeEngineServer(messages=[], socket_path=path, auth_key=KEY)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        time.sleep(0.2)
        try:
            connection, _, challenge, client_nonce, reply = _authenticated(path)
            assert reply["type"] == "hello_ack", reply
            assert auth.verify(auth.hello_ack_mac(KEY, challenge["nonce"], client_nonce), reply["auth"]["mac"])
            connection.close()

            connection, reader = _open(path)
            json.loads(reader.readline())
            _send(connection, _hello())
            assert json.loads(reader.readline())["reason"] == "auth_failed"
            connection.close()
        finally:
            server.close()


# --------------------------------------------------------------------------
# forget_person
# --------------------------------------------------------------------------

MARKER = b"FOTO-WAJAH-RAHASIA-EMP017-" * 40


def _db_bytes(path: Path) -> bytes:
    data = b""
    for suffix in ("", "-wal", "-shm", "-journal"):
        candidate = Path(str(path) + suffix)
        if candidate.exists():
            data += candidate.read_bytes()
    return data


def test_foto_wajah_yang_dihapus_tidak_tersisa_di_berkas(tmp_path):
    """DELETE biasa hanya menandai halaman bebas; tanpa secure_delete foto masih
    bisa dibaca dari berkas SQLite atau -wal setelah 'dihapus'."""
    from engine.store.references import SqliteReferenceStore

    path = tmp_path / "refs.sqlite3"
    store = SqliteReferenceStore(path, "auraface-v1")
    try:
        store.set_roster({"emp_017": 1, "emp_002": 1})
        vector = np.ones(512, dtype=np.float32) / np.sqrt(512)
        store.add_reference("emp_017", vector, MARKER, 0.9)
        store.add_reference("emp_002", vector, b"foto-lain" * 50, 0.9)
        assert MARKER in _db_bytes(path), "prasyarat: penanda tertulis di berkas"

        assert store.delete_person("emp_017") == 1
        assert MARKER not in _db_bytes(path), "foto wajah masih bisa dipulihkan dari berkas"
        assert len(store.records("emp_002")) == 1, "orang lain tidak boleh ikut terhapus"
    finally:
        store.close()


def test_forget_person_dijawab_bukti_dan_idempoten(tmp_path):
    from engine.config import load_config
    from engine.identity import MatrixMatcher
    from engine.runtime.service import EngineRuntime, RuntimeOptions
    from engine.store.references import SqliteReferenceStore

    store = SqliteReferenceStore(tmp_path / "refs.sqlite3", "auraface-v1")
    store.set_roster({"emp_017": 1})
    vector = np.ones(512, dtype=np.float32) / np.sqrt(512)
    for _ in range(3):
        store.add_reference("emp_017", vector, MARKER, 0.9)
    matcher = MatrixMatcher(store)
    matcher.rebuild()
    assert matcher.person_count == 1

    runtime = EngineRuntime(
        config=load_config("engine/config/default_config.yaml"),
        options=RuntimeOptions(tcp=None),
        recognize=lambda *_: None, reference_store=store, matcher=matcher,
    )
    validator = SchemaValidator()
    try:
        first = runtime._on_forget_person({"type": "forget_person", "v": 1,
                                           "request_id": "f-1", "person_id": "emp_017"})
        assert first["removed_references"] == 3 and first["request_id"] == "f-1"
        assert validator.validate_message({**first, "channel": "control"}) == []
        assert matcher.person_count == 0, "matriks wajib dibangun ulang tanpa orang itu"

        again = runtime._on_forget_person({"type": "forget_person", "v": 1,
                                           "request_id": "f-2", "person_id": "emp_017"})
        assert again["removed_references"] == 0
    finally:
        runtime.close()
        store.close()


def test_forget_person_tanpa_store_tetap_menjawab():
    from engine.config import load_config
    from engine.runtime.service import EngineRuntime, RuntimeOptions

    runtime = EngineRuntime(config=load_config("engine/config/default_config.yaml"),
                            options=RuntimeOptions(tcp=None))
    try:
        reply = runtime._on_forget_person({"type": "forget_person", "v": 1,
                                           "request_id": "f-9", "person_id": "emp_1"})
        assert reply["type"] == "forget_result" and reply["removed_references"] == 0
    finally:
        runtime.close()


# --------------------------------------------------------------------------
# engine.health fase 1
# --------------------------------------------------------------------------


def test_health_membawa_outbox_dan_disk(tmp_path):
    from engine.config import load_config
    from engine.runtime.service import EngineRuntime, RuntimeOptions

    runtime = EngineRuntime(
        config=load_config("engine/config/default_config.yaml"),
        options=RuntimeOptions(tcp=None, outbox_path=str(tmp_path / "outbox.sqlite3")),
    )
    try:
        runtime._emit_health(time.time())
        health = runtime.api._outbox.since(0, 10)[-1]
        assert health["type"] == "engine.health"
        assert health["outbox_depth"] >= 0
        assert health["disk_free_mb"] > 0
        assert SchemaValidator().validate_message(health, expected_channel="events") == []
    finally:
        runtime.close()
