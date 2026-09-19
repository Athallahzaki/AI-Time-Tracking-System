"""Server NDJSON: memancarkan skenario ke socket, dengan outbox dan replay.

Satu socket membawa ketiga kanal, dibedakan field `channel` (ENGINE_PROTOCOL
§1 mengizinkan keduanya; satu socket lebih mudah di-`nc` dan lebih mudah
dipasang backend).

Yang dimodelkan sungguhan di sini, karena inilah yang bikin backend patah:

- **Outbox dan replay.** Event disimpan dengan seq; `hello` membawa
  `last_event_seq` dan engine mengulang dari nomor berikutnya. Kalau outbox
  sudah dipangkas melewati titik itu, engine mengirim `replay_gap` lebih dulu —
  dan backend yang memperlakukannya sebagai "tidak ada kejadian" akan ketahuan
  di skenario 7, bukan di produksi.
- **Kanal `view` boleh hilang.** `--chaos drop_view=0.3` membuangnya secara
  acak. Event domain tidak pernah dibuang.
- **Engine tidak pernah memblok menunggu backend.** Socket disetel non-blocking
  untuk kanal view; kalau buffer penuh, frame dibuang dan engine jalan terus.
"""

from __future__ import annotations

import json
import logging
import os
import random
import socket
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("fake_engine.server")

Message = Tuple[str, Dict[str, Any]]


class Outbox:
    """Log event durabel, in-memory. `trim` mensimulasikan retensi habis."""

    def __init__(self) -> None:
        self._events: List[Dict[str, Any]] = []
        self._oldest_seq = 1

    def append(self, payload: Dict[str, Any]) -> None:
        self._events.append(payload)

    def trim(self, keep_from_seq: int) -> None:
        self._events = [e for e in self._events if e.get("seq", 0) >= keep_from_seq]
        self._oldest_seq = keep_from_seq

    @property
    def oldest_available_seq(self) -> int:
        if not self._events:
            return self._oldest_seq
        return min(e.get("seq", self._oldest_seq) for e in self._events)

    def since(self, last_event_seq: int) -> List[Dict[str, Any]]:
        return [e for e in self._events if e.get("seq", 0) > last_event_seq]


class FakeEngineServer:
    def __init__(
        self,
        messages: List[Message],
        socket_path: Optional[str] = None,
        tcp: Optional[Tuple[str, int]] = None,
        speed: float = 1.0,
        loop: bool = False,
        seed: int = 42,
        chaos: Optional[Dict[str, float]] = None,
        engine_version: str = "fake-0.1.0",
    ) -> None:
        if not socket_path and not tcp:
            raise ValueError("butuh --socket atau --tcp")
        self._messages = messages
        self._socket_path = socket_path
        self._tcp = tcp
        self._speed = max(speed, 0.001)
        self._loop = loop
        self._chaos = chaos or {}
        self._random = random.Random(seed)
        self._engine_version = engine_version

        self._outbox = Outbox()
        self._server: Optional[socket.socket] = None
        self._stop = threading.Event()
        # Posisi pemutaran skenario, dipertahankan LINTAS koneksi. Engine
        # sungguhan tidak mengulang harinya dari pagi setiap kali backend
        # di-deploy ulang; kalau di sini ia mengulang, `reconnect-replay` jadi
        # menguji sesuatu yang tidak akan pernah terjadi, dan event yang sama
        # masuk outbox dua kali.
        self._cursor = 0

    # ---------------- socket ----------------

    def _listen(self) -> socket.socket:
        if self._socket_path:
            if os.path.exists(self._socket_path):
                os.unlink(self._socket_path)
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(self._socket_path)
        else:
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(self._tcp)
        server.listen(1)
        return server

    def serve_forever(self) -> None:
        self._server = self._listen()
        where = self._socket_path or f"{self._tcp[0]}:{self._tcp[1]}"
        logger.info("fake_engine mendengarkan di %s", where)

        try:
            while not self._stop.is_set():
                connection, _ = self._server.accept()
                logger.info("backend tersambung")
                try:
                    self._serve_one(connection)
                except (BrokenPipeError, ConnectionResetError):
                    logger.info("backend memutus koneksi")
                finally:
                    # `makefile()` memegang referensi ke fd yang sama, jadi
                    # `close()` sendirian tidak mengirim EOF dan klien
                    # menggantung sampai timeout. `shutdown()` yang benar-benar
                    # menutup arah tulisnya.
                    try:
                        connection.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                    connection.close()
                    logger.info("skenario habis, koneksi ditutup")
                if not self._loop:
                    # Tetap menerima koneksi berikutnya: justru reconnect yang
                    # ingin diuji. Yang berhenti cuma pemutaran skenarionya.
                    continue
        finally:
            self.close()

    def close(self) -> None:
        self._stop.set()
        if self._server is not None:
            self._server.close()
            self._server = None
        if self._socket_path and os.path.exists(self._socket_path):
            os.unlink(self._socket_path)

    # ---------------- sesi ----------------

    def _serve_one(self, connection: socket.socket) -> None:
        reader = connection.makefile("r", encoding="utf-8")

        first = reader.readline()
        if not first:
            return
        try:
            hello = json.loads(first)
        except json.JSONDecodeError:
            self._send(connection, "control", {"type": "ack", "v": 1, "ts": _now(),
                                               "in_reply_to": "hello", "accepted": False,
                                               "reason": "json tidak valid"})
            return

        if hello.get("type") != "hello":
            # Kontrak: hello wajib pertama. Menolak di sini lebih baik daripada
            # diam-diam melanjutkan, karena backend yang lupa hello juga lupa
            # mengirim last_event_seq dan akan kehilangan event tanpa sadar.
            self._send(connection, "control", {"type": "ack", "v": 1, "ts": _now(),
                                               "in_reply_to": hello.get("type", "?"),
                                               "accepted": False,
                                               "reason": "hello wajib pesan pertama"})
            return

        last_event_seq = int(hello.get("last_event_seq", 0))
        oldest = self._outbox.oldest_available_seq

        self._send(connection, "control", {
            "type": "hello_ack", "v": 1, "ts": _now(),
            "protocol_version": 1,
            "engine_version": self._engine_version,
            "models": {
                "detector": "fake-detector",
                "embedder": "fake-embedder",
                "embedding_version": "fake-v1",
                "tracker": "fake-tracker",
            },
            "oldest_available_seq": oldest,
        })

        if last_event_seq > 0:
            if last_event_seq < oldest - 1 and self._cursor > 0:
                self._send(connection, "control", {
                    "type": "replay_gap", "v": 1, "ts": _now(),
                    "from_seq": last_event_seq, "to_seq": oldest,
                })
            for event in self._outbox.since(last_event_seq):
                self._send(connection, "events", event)

        threading.Thread(
            target=self._read_control, args=(connection, reader), daemon=True
        ).start()

        self._play(connection)

    def _read_control(self, connection: socket.socket, reader) -> None:
        for line in reader:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            for reply in self._handle_control(message):
                try:
                    self._send(connection, "control", reply)
                except OSError:
                    return

    def _handle_control(self, message: Dict[str, Any]) -> List[Dict[str, Any]]:
        message_type = message.get("type")

        if message_type in {"set_cameras", "set_roster"}:
            # Di-ack segera; hasilnya menyusul sebagai event. Membuka RTSP bisa
            # makan lima detik dan bisa gagal -- RPC yang menunggu sampai semua
            # stream tersambung akan menggantung backend di startup.
            return [{"type": "ack", "v": 1, "ts": _now(),
                     "in_reply_to": message_type, "accepted": True}]

        if message_type == "enroll":
            return [self._enroll_result(message)]

        return [{"type": "ack", "v": 1, "ts": _now(),
                 "in_reply_to": message_type or "?", "accepted": False,
                 "reason": "tidak dikenal"}]

    def _enroll_result(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Balasan enrollment yang deterministik dari isi permintaannya.

        Aturannya dibuat supaya backend dan frontend bisa menguji setiap jalur
        penolakan tanpa model apa pun: id gambar yang memuat `blurry`,
        `too_small`, `no_face` atau `dup` ditolak dengan alasan itu, dan
        person_id yang berakhiran `9` dianggap bertabrakan.
        """
        images = []
        accepted_count = 0
        for image in message.get("images", []):
            image_id = str(image.get("id", ""))
            reason = None
            for marker in ("blurry", "too_small", "extreme_pose", "bad_lighting",
                           "no_face", "multiple_faces"):
                if marker in image_id:
                    reason = marker
                    break
            if reason is None and "dup" in image_id:
                reason = "duplicate_of:img1"

            if reason is None:
                accepted_count += 1
                images.append({"id": image_id, "accepted": True, "quality": 0.81})
            else:
                entry = {"id": image_id, "accepted": False, "reason": reason}
                if reason.startswith("duplicate_of"):
                    entry["similarity"] = 0.94
                images.append(entry)

        person_id = str(message.get("person_id", ""))
        result: Dict[str, Any] = {
            "type": "enroll_result", "v": 1, "ts": _now(),
            "request_id": message.get("request_id", ""),
            "embedding_version": "fake-v1",
            "images": images,
        }

        if person_id.endswith("9"):
            result.update(accepted=False, reason="collision",
                          collides_with="4802", collision_similarity=0.83)
        elif accepted_count < 3:
            result.update(accepted=False, reason="insufficient_references")
        else:
            result.update(accepted=True, reason="ok")
        return result

    # ---------------- pemutaran ----------------

    def _play(self, connection: socket.socket) -> None:
        started = time.monotonic()
        base: Optional[float] = None

        while self._cursor < len(self._messages):
            channel, payload = self._messages[self._cursor]
            self._cursor += 1

            if channel == "_harness":
                if payload.get("action") == "disconnect":
                    logger.info("skenario memutus koneksi di t=%.1f", payload.get("at", 0))
                    return
                if payload.get("action") == "trim_outbox":
                    self._outbox.trim(int(payload.get("keep_from_seq", 1)))
                continue

            when = _scenario_time(payload)
            if base is None:
                base = when
            target = started + (when - base) / self._speed
            delay = target - time.monotonic()
            if delay > 0:
                time.sleep(delay)

            if channel == "events":
                self._outbox.append(payload)

            if channel == "view" and self._random.random() < self._chaos.get("drop_view", 0.0):
                continue

            try:
                self._send(connection, channel, payload)
            except OSError:
                return

        if self._loop:
            logger.info("skenario habis, mengulang dari awal")
            self._cursor = 0

    @staticmethod
    def _send(connection: socket.socket, channel: str, payload: Dict[str, Any]) -> None:
        line = json.dumps({**payload, "channel": channel}, ensure_ascii=False) + "\n"
        connection.sendall(line.encode("utf-8"))


def _now() -> str:
    import datetime as dt
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _scenario_time(payload: Dict[str, Any]) -> float:
    for key in ("pts", "start_pts"):
        if key in payload:
            return float(payload[key])
    return 0.0
