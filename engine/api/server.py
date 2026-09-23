"""Gerbang tunggal engine ke luar: socket NDJSON, tiga kanal, outbox, replay.

Modul lain DILARANG menulis ke socket. Itu bukan aturan gaya — kondisi sebelum
pemisahan proses punya `EngineWorker` yang mengiterasi `self.engine._listeners`
dan melakukan dispatch dengan `type(listener).__name__`, sehingga mengganti nama
satu kelas membuat event hook diam-diam tidak terpasang: tanpa error, tanpa log,
absensi hanya berhenti tercatat. Satu gerbang berarti satu tempat yang bisa
salah, dan satu tempat yang bisa diuji.

**Engine tidak pernah memblok menunggu backend.** Ini yang paling mudah dilanggar
tanpa sadar, karena `sendall` ke socket yang bufernya penuh akan menunggu dengan
sabar sementara frame loop berhenti dan kamera lima ruangan tidak diproses.
Jadi: pengiriman dikerjakan thread tersendiri, kanal `view` punya antrian
terbatas yang membuang saat penuh, dan `emit_*` tidak pernah menunggu siapa pun.
Yang haram adalah membuang event domain — itu produknya; dashboard cuma tampilan.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import socket
import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple

from .outbox import Outbox, SqliteOutbox, _OutboxBase

logger = logging.getLogger("engine.api")

ControlHandler = Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]

# Kanal view boleh tertinggal sejauh ini sebelum frame lama dibuang. Kecil
# dengan sengaja: kalau backend tertinggal lebih dari sekejap, kotak lama tidak
# berguna lagi -- orangnya sudah pindah, dan kotak yang lebih baru lebih
# berharga daripada yang lebih lengkap.
VIEW_QUEUE_MAX = 120
EVENT_QUEUE_MAX = 10_000


class EngineApi:
    def __init__(
        self,
        outbox: Optional[_OutboxBase] = None,
        engine_version: str = "0.1.0",
        models: Optional[Dict[str, str]] = None,
        protocol_version: int = 1,
    ) -> None:
        self._outbox = outbox if outbox is not None else Outbox()
        self._engine_version = engine_version
        self._models = models or {
            "detector": "unset", "embedder": "unset", "embedding_version": "unset",
        }
        self._protocol_version = protocol_version

        # Event TIDAK lewat antrian yang bisa dibuang. Pengiriman event berbasis
        # kursor ke outbox: thread kirim membaca `outbox.since(kursor)`, jadi
        # tidak ada satu pun event yang bisa "diambil lalu dibuang" ketika
        # koneksi sedang kosong (itu penyebab event hilang saat handshake).
        self._wake = threading.Event()
        self._cursor = 0
        self._generation = 0
        self._views: "queue.Queue[Dict[str, Any]]" = queue.Queue(maxsize=VIEW_QUEUE_MAX)
        self._handlers: Dict[str, ControlHandler] = {}

        self._connection: Optional[socket.socket] = None
        self._connection_lock = threading.Lock()
        # Satu kunci tulis untuk SEMUA penulisan ke socket: handshake (thread
        # accept), thread kirim, dan balasan kontrol (thread baca). `sendall`
        # dari beberapa thread tidak atomik dan bisa menyisipkan NDJSON.
        self._write_lock = threading.Lock()
        self._server: Optional[socket.socket] = None
        self._sender: Optional[threading.Thread] = None
        self._stop = threading.Event()

        self._dropped_views = 0
        self._sent_events = 0

    # ---------------- pemancaran ----------------

    def emit_event(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Nomori, simpan durabel, lalu kirim kalau ada yang mendengarkan.

        Urutannya penting dan tidak boleh dibalik: disimpan DULU, dikirim
        kemudian. Event yang terkirim tapi belum tersimpan akan hilang kalau
        engine mati sebelum sempat menulisnya, dan backend tidak punya cara
        tahu — ia sudah menerimanya, jadi ia tidak akan memintanya lagi.
        """
        stored = self._outbox.append(message)
        self._wake.set()
        return stored

    def emit_view(self, message: Dict[str, Any]) -> bool:
        """Best-effort. `False` berarti dibuang, dan itu keadaan normal."""
        try:
            self._views.put_nowait(message)
            return True
        except queue.Full:
            # Buang yang TERTUA, pertahankan yang terbaru: kotak dari posisi
            # yang sudah ditinggalkan orangnya tidak lebih berguna daripada
            # kotak dari posisinya sekarang.
            try:
                self._views.get_nowait()
                self._views.put_nowait(message)
            except queue.Empty:
                pass
            self._dropped_views += 1
            return False

    @property
    def metrics(self) -> Dict[str, float]:
        return {
            "outbox_depth": float(len(self._outbox)),
            "event_queue": float(max(0, self._outbox.latest_seq - self._cursor)),
            "view_queue": float(self._views.qsize()),
            "dropped_views": float(self._dropped_views),
            "sent_events": float(self._sent_events),
            "connected": 1.0 if self._connection is not None else 0.0,
            "latest_seq": float(self._outbox.latest_seq),
        }

    # ---------------- control ----------------

    def on_control(self, message_type: str, handler: ControlHandler) -> "EngineApi":
        """Daftarkan penangan perintah backend.

        `api/` tidak mengimplementasikan `set_cameras` atau `enroll` sendiri --
        itu milik ingest dan identity. Ia cuma meneruskan, dan mengembalikan
        ack segera. Perintah di-ack saat diterima, bukan saat selesai: membuka
        RTSP bisa makan lima detik dan bisa gagal, dan backend yang menunggu
        akan menggantung di startup.
        """
        self._handlers[message_type] = handler
        return self

    # ---------------- socket ----------------

    def listen(self, socket_path: Optional[str] = None, tcp: Optional[Tuple[str, int]] = None) -> None:
        if not socket_path and not tcp:
            raise ValueError("butuh socket_path atau tcp")

        if socket_path:
            if os.path.exists(socket_path):
                os.unlink(socket_path)
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(socket_path)
        else:
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(tcp)

        server.listen(1)
        self._server = server
        self._socket_path = socket_path

        self._sender = threading.Thread(target=self._send_loop, daemon=True, name="engine-api-send")
        self._sender.start()

    def serve_forever(self) -> None:
        if self._server is None:
            raise RuntimeError("panggil listen() dulu")

        while not self._stop.is_set():
            try:
                connection, _ = self._server.accept()
            except OSError:
                break

            logger.info("backend tersambung")
            try:
                self._handshake(connection)
            except (BrokenPipeError, ConnectionResetError, OSError) as error:
                logger.info("jabat tangan gagal: %s", error)
                self._close_connection(connection)

    def close(self) -> None:
        self._stop.set()
        with self._connection_lock:
            connection, self._connection = self._connection, None
        if connection:
            self._close_connection(connection)
        if self._server is not None:
            self._server.close()
            self._server = None
        if getattr(self, "_socket_path", None) and os.path.exists(self._socket_path):
            os.unlink(self._socket_path)

    # ---------------- internal ----------------

    def _handshake(self, connection: socket.socket) -> None:
        reader = connection.makefile("r", encoding="utf-8")
        first = reader.readline()
        if not first:
            self._close_connection(connection)
            return

        hello = json.loads(first)
        if hello.get("type") != "hello":
            # Backend yang lupa hello juga lupa mengirim `last_event_seq`, dan
            # akan kehilangan event tanpa sadar. Menolak di sini lebih baik
            # daripada melayani koneksi yang sudah salah sejak baris pertama.
            self._write(connection, {
                "type": "ack", "v": 1, "ts": _now(), "channel": "control",
                "in_reply_to": hello.get("type", "?"), "accepted": False,
                "reason": "hello wajib pesan pertama",
            })
            self._close_connection(connection)
            return

        last_event_seq = int(hello.get("last_event_seq", 0))

        hello_ack = {
            "type": "hello_ack", "v": 1, "ts": _now(), "channel": "control",
            "protocol_version": self._protocol_version,
            "engine_version": self._engine_version,
            "models": dict(self._models),
            "oldest_available_seq": self._outbox.oldest_available_seq,
        }
        outbox_id = getattr(self._outbox, "outbox_id", None)
        if outbox_id:
            # Identitas outbox. Backend memakainya untuk tahu bahwa penomoran
            # `seq` dimulai ulang (berkas outbox dihapus / engine in-memory
            # restart) alih-alih membuang event baru sebagai "sudah dilihat".
            hello_ack["outbox_id"] = outbox_id

        with self._write_lock:
            self._write(connection, hello_ack)
            gap = self._outbox.gap_for(last_event_seq)
            if gap is not None:
                gap["ts"] = _now()
                gap["channel"] = "control"
                self._write(connection, gap)
                logger.warning("lubang data: seq %s..%s", gap["from_seq"], gap["to_seq"])

            # Koneksi dan kursor dipasang atomik, di bawah kunci tulis yang
            # sama: tidak ada pesan lain yang bisa mendahului hello_ack, dan
            # replay dikerjakan thread kirim dari kursor ini -- satu jalur,
            # tanpa snapshot yang bisa ketinggalan event.
            with self._connection_lock:
                previous = self._connection
                self._connection = connection
                self._cursor = max(0, last_event_seq)
                self._generation += 1

        if previous is not None and previous is not connection:
            self._close_connection(previous)
        self._wake.set()

        threading.Thread(
            target=self._read_loop, args=(connection, reader), daemon=True, name="engine-api-read"
        ).start()

    def _read_loop(self, connection: socket.socket, reader) -> None:
        try:
            for line in reader:
                line = line.strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                self._dispatch(connection, message)
        except OSError:
            pass
        finally:
            with self._connection_lock:
                if self._connection is connection:
                    self._connection = None
            self._close_connection(connection)

    def _dispatch(self, connection: socket.socket, message: Dict[str, Any]) -> None:
        message_type = message.get("type")

        if message_type == "ack":
            # Pemangkasan outbox hanya boleh terjadi setelah backend menyatakan
            # sudah menerima (§6.5). Memangkas berdasarkan waktu saja berarti
            # membuang event yang belum pernah sampai.
            through = message.get("through_seq")
            if isinstance(through, int) and hasattr(self._outbox, "ack"):
                removed = self._outbox.ack(through)
                logger.debug("outbox dipangkas sampai seq %s (%s baris)", through, removed)
            return

        handler = self._handlers.get(message_type or "")
        if handler is None:
            self._send(connection, {
                "type": "ack", "v": 1, "ts": _now(), "channel": "control",
                "in_reply_to": message_type or "?", "accepted": False, "reason": "tidak dikenal",
            })
            return

        try:
            reply = handler(message)
        except Exception:
            logger.exception("penangan `%s` gagal", message_type)
            reply = {"type": "ack", "v": 1, "ts": _now(), "channel": "control",
                     "in_reply_to": message_type, "accepted": False, "reason": "kesalahan internal"}

        if reply is None:
            reply = {"type": "ack", "v": 1, "ts": _now(), "channel": "control",
                     "in_reply_to": message_type, "accepted": True}

        reply.setdefault("channel", "control")
        self._send(connection, reply)

    SEND_BATCH = 500
    VIEWS_PER_ROUND = 8

    def _send_loop(self) -> None:
        """Satu penulis untuk event dan view. Event selalu didahulukan.

        Event dibaca dari outbox mulai kursor; kursor maju hanya setelah
        penulisan berhasil ke koneksi yang SAMA (dicek lewat `_generation`).
        Kalau koneksi berganti di tengah batch, sisa batch ditinggalkan dan
        handshake berikutnya sudah memasang kursor dari `last_event_seq`.
        """
        while not self._stop.is_set():
            self._wake.wait(0.05)
            self._wake.clear()

            with self._connection_lock:
                connection = self._connection
                cursor = self._cursor
                generation = self._generation

            if connection is None:
                # View memang boleh hilang; event tetap aman di outbox.
                self._discard_views()
                continue

            pending = self._outbox.since(cursor, self.SEND_BATCH) if self._outbox.latest_seq > cursor else []
            try:
                for event in pending:
                    with self._write_lock:
                        with self._connection_lock:
                            if self._generation != generation:
                                break
                        self._write(connection, event, "events")
                        with self._connection_lock:
                            if self._generation == generation:
                                self._cursor = max(self._cursor, int(event.get("seq", 0)))
                    self._sent_events += 1

                if len(pending) >= self.SEND_BATCH:
                    self._wake.set()      # masih ada backlog; view menunggu
                    continue

                for _ in range(self.VIEWS_PER_ROUND):
                    try:
                        view = self._views.get_nowait()
                    except queue.Empty:
                        break
                    with self._write_lock:
                        with self._connection_lock:
                            if self._generation != generation:
                                break
                        self._write(connection, view, "view")
                if not self._views.empty():
                    self._wake.set()
            except OSError:
                with self._connection_lock:
                    if self._connection is connection:
                        self._connection = None

    def _discard_views(self) -> None:
        while True:
            try:
                self._views.get_nowait()
            except queue.Empty:
                return

    def _send(self, connection: socket.socket, message: Dict[str, Any], channel: Optional[str] = None) -> None:
        with self._write_lock:
            self._write(connection, message, channel)

    @staticmethod
    def _write(connection: socket.socket, message: Dict[str, Any], channel: Optional[str] = None) -> None:
        payload = dict(message)
        if channel:
            payload["channel"] = channel
        connection.sendall((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))

    @staticmethod
    def _close_connection(connection: socket.socket) -> None:
        try:
            connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        connection.close()


def _now() -> str:
    import datetime as dt
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
