"""Kanal event durabel: tidak ada event yang hilang diam-diam.

Tes ini memakai socket TCP sungguhan ke `engine.api.EngineApi` — batas proses
yang sama dengan produksi, hanya tanpa kamera.
"""
from __future__ import annotations

import socket
import threading
import time

import pytest

from backend.core import database
from backend.services import engine_client as client_module
from backend.services.engine_client import EngineClient, SequenceGapError, OutboxChangedError
from engine.api import EngineApi
from engine.api.outbox import Outbox, SqliteOutbox


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "backend.db")
    database.init_database()
    return database


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def camera_online(i: int) -> dict:
    t = "2026-09-23T01:00:%02d.000Z" % (i % 60)
    return {"type": "camera.online", "v": 1, "ts": t, "at": t, "camera_id": "r1",
            "fps": 10.0, "stream_epoch": 0, "pts_wallclock_offset": 1.0}


def start_engine(outbox) -> tuple[EngineApi, int]:
    port = free_port()
    api = EngineApi(outbox=outbox, engine_version="t",
                    models={"detector": "d", "embedder": "unset", "embedding_version": "unset"})
    api.listen(tcp=("127.0.0.1", port))
    threading.Thread(target=api.serve_forever, daemon=True).start()
    return api, port


def connect(port: int, received: list, outbox_holder=None) -> EngineClient:
    client = EngineClient(port=port)

    def handler(message):
        database.save_protocol_event(0.0, message["type"], message, message["seq"], client.outbox_id)
        received.append(message["seq"])

    client.set_event_handler(handler)
    for _ in range(3):
        try:
            client.connect()
            break
        except OutboxChangedError:
            continue
    client.start_receiver()
    return client


def wait_for(predicate, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_engine_restart_with_new_outbox_is_not_dropped(db):
    received: list = []
    api, port = start_engine(Outbox())
    client = connect(port, received)
    for i in range(5):
        api.emit_event(camera_online(i))
    assert wait_for(lambda: len(received) == 5)
    client.close()
    api.close()

    api2, port2 = start_engine(Outbox())          # new in-memory outbox, seq restarts at 1
    received2: list = []
    client2 = EngineClient(port=port2)
    client2.set_event_handler(lambda m: (database.save_protocol_event(
        0.0, m["type"], m, m["seq"], client2.outbox_id), received2.append(m["seq"])))
    for i in range(5, 12):
        api2.emit_event(camera_online(i))
    with pytest.raises(OutboxChangedError):
        client2.connect()                         # detects the reset, asks to reconnect
    client2.connect()
    client2.start_receiver()
    assert wait_for(lambda: len(received2) == 7), received2
    assert received2 == [1, 2, 3, 4, 5, 6, 7]
    client2.close()
    api2.close()


def test_event_emitted_during_handshake_is_delivered(db):
    outbox = Outbox()
    api, port = start_engine(outbox)
    for i in range(3):
        api.emit_event(camera_online(i))
    time.sleep(0.2)

    original = outbox.since
    fired = {"done": False}

    def since_with_camera_thread(last, limit=None):
        out = original(last, limit)
        if not fired["done"]:
            fired["done"] = True
            api.emit_event(camera_online(10))     # a camera emits mid-handshake
            time.sleep(0.2)
        return out

    outbox.since = since_with_camera_thread
    received: list = []
    client = connect(port, received)
    time.sleep(0.3)
    api.emit_event(camera_online(11))
    assert wait_for(lambda: len(received) == 5), received
    assert received == [1, 2, 3, 4, 5]
    client.close()
    api.close()


def test_close_does_not_deadlock_while_receiver_is_blocked(db):
    api, port = start_engine(Outbox())
    client = connect(port, [])
    time.sleep(0.1)
    done = threading.Event()
    threading.Thread(target=lambda: (client.close(), done.set()), daemon=True).start()
    assert done.wait(3.0), "close() hung while the receiver was in readline()"
    api.close()


class _FakeSocket:
    def __init__(self):
        self.sent = []

    def sendall(self, payload):
        self.sent.append(payload.decode())


def _offline_client() -> EngineClient:
    client = EngineClient()
    client._socket = _FakeSocket()
    client.connected = True
    return client


def test_seq_gap_triggers_replay_instead_of_silent_acceptance(db):
    client = _offline_client()
    client.set_event_handler(lambda m: None)
    client.handle_message({**camera_online(1), "seq": 1})
    with pytest.raises(SequenceGapError):
        client.handle_message({**camera_online(3), "seq": 3})
    assert client.last_event_seq == 1


def test_gap_announced_by_replay_gap_is_accepted(db):
    client = _offline_client()
    client.set_event_handler(lambda m: None)
    client.handle_message({**camera_online(1), "seq": 1})
    client.handle_message({"type": "replay_gap", "v": 1, "ts": "2026-09-23T01:00:00Z",
                           "channel": "control", "from_seq": 1, "to_seq": 50})
    client.handle_message({**camera_online(2), "seq": 50})
    assert client.last_event_seq == 50


def test_poison_event_is_dead_lettered_and_stream_continues(db):
    client = _offline_client()

    def handler(message):
        if message["seq"] == 2:
            raise RuntimeError("boom")

    client.set_event_handler(handler)
    for seq in (1, 2, 3):
        client.handle_message({**camera_online(seq), "seq": seq})
    assert client.last_event_seq == 3
    letters = database.get_dead_letters()
    assert [item["seq"] for item in letters] == [2]
    assert '"through_seq":3' in client._socket.sent[-1]


def test_invalid_view_frame_does_not_drop_connection(db):
    client = _offline_client()
    client.handle_message({"type": "view.frame", "channel": "view", "garbage": True})
    assert client.connected is True


def test_sqlite_outbox_keeps_identity_and_numbering(tmp_path):
    path = tmp_path / "outbox.sqlite3"
    first = SqliteOutbox(path)
    for i in range(3):
        first.append(camera_online(i))
    first.ack(3)
    identity = first.outbox_id
    first.close()

    reopened = SqliteOutbox(path)
    assert reopened.outbox_id == identity
    assert reopened.append(camera_online(4))["seq"] == 4
    reopened.close()


def test_runtime_uses_durable_outbox_when_path_given(tmp_path):
    from engine.runtime.service import EngineRuntime, RuntimeOptions
    runtime = EngineRuntime(options=RuntimeOptions(tcp=None, outbox_path=str(tmp_path / "o.db")))
    assert isinstance(runtime.api._outbox, SqliteOutbox)
    runtime.api._outbox.close()
