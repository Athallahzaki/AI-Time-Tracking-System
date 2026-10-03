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
import struct
import sys
import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple

from contracts import handshake_auth

from .outbox import Outbox, SqliteOutbox, _OutboxBase

logger = logging.getLogger("engine.api")

ControlHandler = Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]

# Kanal view boleh tertinggal sejauh ini sebelum frame lama dibuang. Kecil
# dengan sengaja: kalau backend tertinggal lebih dari sekejap, kotak lama tidak
# berguna lagi -- orangnya sudah pindah, dan kotak yang lebih baru lebih
# berharga daripada yang lebih lengkap.
VIEW_QUEUE_MAX = 120
EVENT_QUEUE_MAX = 10_000

# Klien yang tersambung wajib mengirim `hello` dalam batas ini. Tanpa batas,
# satu koneksi TCP yang diam (port scanner, laptop yang nyangkut) menahan
# handshake selamanya.
HANDSHAKE_TIMEOUT_SECONDS = 5.0
# `sendall` ke backend yang berhenti membaca (mati tanpa FIN, jaringan putus)
# akan menunggu selamanya sambil memegang kunci tulis. Lewat batas ini koneksi
# diputus; event tetap aman di outbox dan diputar ulang saat backend kembali.
SEND_TIMEOUT_SECONDS = 15.0
# Keepalive TCP: peer yang hilang terdeteksi setelah +-IDLE + INTERVAL*COUNT.
KEEPALIVE_IDLE_SECONDS = 30
KEEPALIVE_INTERVAL_SECONDS = 10
KEEPALIVE_COUNT = 3
# `hello` itu kecil. Baris pertama yang lebih panjang dari ini bukan backend.
MAX_HELLO_CHARS = 64 * 1024
ACCEPT_POLL_SECONDS = 0.5   # seberapa cepat Ctrl+C / close() terasa saat menunggu klien


class EngineApi:
    def __init__(
        self,
        outbox: Optional[_OutboxBase] = None,
        engine_version: str = "0.1.0",
        models: Optional[Dict[str, str]] = None,
        protocol_version: int = 1,
        handshake_timeout: float = HANDSHAKE_TIMEOUT_SECONDS,
        send_timeout: Optional[float] = SEND_TIMEOUT_SECONDS,
        keepalive: bool = True,
        auth_key: Optional[str] = None,
    ) -> None:
        self._outbox = outbox if outbox is not None else Outbox()
        self._handshake_timeout = float(handshake_timeout)
        self._send_timeout = send_timeout
        self._keepalive = keepalive
        # Kunci bersama (P3). None = autentikasi mati, urutan handshake lama.
        # Kunci yang terlalu pendek ditolak SEKARANG, bukan saat backend pertama
        # tersambung: engine yang salah konfigurasi wajib gagal start.
        if auth_key is not None:
            handshake_auth._key_bytes(auth_key)
        self._auth_key = auth_key
        self._auth_failures = 0
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
            "auth_failures": float(self._auth_failures),
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

        server.listen(8)
        self._server = server
        self._socket_path = socket_path

        self._sender = threading.Thread(target=self._send_loop, daemon=True, name="engine-api-send")
        self._sender.start()

    def serve_forever(self) -> None:
        if self._server is None:
            raise RuntimeError("panggil listen() dulu")

        # accept() TANPA batas waktu tidak bisa diinterupsi Ctrl+C di Windows:
        # handler sinyal Python hanya jalan saat thread utama kembali ke bytecode,
        # dan Winsock accept() tidak kembali sampai ada klien. Engine yang sedang
        # menunggu backend tidak bisa dihentikan. Jadi tunggu dalam potongan pendek.
        server = self._server
        server.settimeout(ACCEPT_POLL_SECONDS)
        while not self._stop.is_set():
            try:
                connection, _ = server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            # Soket hasil accept bisa mewarisi batas waktu soket pendengar;
            # jabat tangan memasang batas waktunya sendiri.
            connection.settimeout(None)

            logger.info("klien tersambung")
            # Handshake TIDAK dikerjakan di thread accept: klien yang lambat
            # atau diam tidak boleh menahan klien berikutnya.
            threading.Thread(
                target=self._handshake_guarded, args=(connection,),
                daemon=True, name="engine-api-handshake",
            ).start()

    def _handshake_guarded(self, connection: socket.socket) -> None:
        try:
            self._handshake(connection)
        except socket.timeout:
            logger.info("klien tidak mengirim hello dalam %.1f dtk; diputus", self._handshake_timeout)
            self._close_connection(connection)
        except OSError as error:
            logger.info("jabat tangan gagal: %s", error)
            self._close_connection(connection)
        except Exception:  # noqa: BLE001 -- baris pertama liar tidak boleh mematikan engine
            logger.warning("jabat tangan ditolak: pesan pertama tidak valid", exc_info=True)
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
        connection.settimeout(self._handshake_timeout)
        server_nonce = None
        if self._auth_key is not None:
            # Tantangan dikirim SEBELUM membaca apa pun: klien yang tidak
            # memegang kunci tidak pernah sampai ke kunci tulis atau kursor.
            server_nonce = handshake_auth.new_nonce()
            self._write(connection, {
                "type": "auth_challenge", "v": 1, "ts": _now(), "channel": "control",
                "nonce": server_nonce, "algorithm": handshake_auth.ALGORITHM,
            })
        reader = connection.makefile("r", encoding="utf-8")
        first = reader.readline(MAX_HELLO_CHARS)
        if not first or not first.endswith("\n"):
            # Kosong = klien menutup; tanpa newline = baris terlalu panjang.
            self._close_connection(connection)
            return

        hello = json.loads(first)
        if not isinstance(hello, dict):
            self._close_connection(connection)
            return
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

        client_nonce = None
        if server_nonce is not None:
            client_nonce = self._verify_hello(hello, server_nonce, last_event_seq)
            if client_nonce is None:
                # Diputus SEBELUM koneksi lama disentuh: klien liar tidak boleh
                # bisa menendang backend sah (E3).
                self._auth_failures += 1
                self._write(connection, {
                    "type": "ack", "v": 1, "ts": _now(), "channel": "control",
                    "in_reply_to": "hello", "accepted": False, "reason": "auth_failed",
                })
                logger.warning("handshake ditolak: autentikasi gagal (%s)", _peer(connection))
                self._close_connection(connection)
                return

        # Sejak sini koneksi dianggap backend: baca tanpa batas waktu (backend
        # boleh diam lama), tapi kirim berbatas dan peer yang hilang terdeteksi.
        connection.settimeout(None)
        self._configure_live_socket(connection)

        # Putus koneksi lama SEBELUM mengambil kunci tulis. Thread kirim bisa
        # sedang tertahan di `sendall` ke koneksi lama sambil memegang kunci
        # itu; shutdown membangunkannya. Urutan sebaliknya (kunci dulu, putus
        # kemudian) membuat backend baru menunggu koneksi lama yang mati.
        with self._connection_lock:
            stale = self._connection
            self._connection = None
            self._generation += 1
        if stale is not None and stale is not connection:
            logger.info("koneksi backend lama diputus untuk handshake baru")
            self._close_connection(stale)

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
        if server_nonce is not None and client_nonce is not None:
            hello_ack["auth"] = {
                "mac": handshake_auth.hello_ack_mac(self._auth_key, server_nonce, client_nonce),
            }

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

    def _verify_hello(self, hello: Dict[str, Any], server_nonce: str, last_event_seq: int) -> Optional[str]:
        """Kembalikan client_nonce bila hello membuktikan kunci; None bila tidak."""
        auth = hello.get("auth")
        if not isinstance(auth, dict):
            return None
        client_nonce, mac = auth.get("client_nonce"), auth.get("mac")
        try:
            expected = handshake_auth.hello_mac(
                self._auth_key, server_nonce, client_nonce,
                str(hello.get("client", "")), last_event_seq,
            )
        except (TypeError, ValueError):
            return None
        if not handshake_auth.verify(expected, mac):
            return None
        return client_nonce

    def _configure_live_socket(self, connection: socket.socket) -> None:
        """Keepalive + batas waktu kirim. Gagal memasang = dicatat, bukan fatal."""
        is_tcp = connection.family in (socket.AF_INET, getattr(socket, "AF_INET6", -1))
        if self._keepalive and is_tcp:
            try:
                connection.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                if hasattr(socket, "SIO_KEEPALIVE_VALS"):  # Windows
                    connection.ioctl(socket.SIO_KEEPALIVE_VALS, (
                        1, KEEPALIVE_IDLE_SECONDS * 1000, KEEPALIVE_INTERVAL_SECONDS * 1000,
                    ))
                else:
                    for name, value in (
                        ("TCP_KEEPIDLE", KEEPALIVE_IDLE_SECONDS),
                        ("TCP_KEEPINTVL", KEEPALIVE_INTERVAL_SECONDS),
                        ("TCP_KEEPCNT", KEEPALIVE_COUNT),
                    ):
                        option = getattr(socket, name, None)
                        if option is not None:
                            connection.setsockopt(socket.IPPROTO_TCP, option, value)
            except OSError:
                logger.warning("keepalive TCP tidak bisa dipasang", exc_info=True)

        if self._send_timeout:
            # SO_SNDTIMEO hanya membatasi KIRIM. `settimeout()` tidak dipakai
            # karena ikut membatasi baca, padahal backend boleh diam lama, dan
            # reader makefile tidak bisa dipakai lagi setelah sekali timeout.
            try:
                if sys.platform == "win32":
                    value = int(self._send_timeout * 1000)  # DWORD milidetik
                    connection.setsockopt(socket.SOL_SOCKET, socket.SO_SNDTIMEO, value)
                else:
                    seconds = int(self._send_timeout)
                    micros = int((self._send_timeout - seconds) * 1_000_000)
                    connection.setsockopt(
                        socket.SOL_SOCKET, socket.SO_SNDTIMEO, struct.pack("ll", seconds, micros)
                    )
            except OSError:
                logger.warning("batas waktu kirim tidak bisa dipasang", exc_info=True)

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


def _peer(connection: socket.socket) -> str:
    try:
        return str(connection.getpeername())
    except OSError:
        return "?"


def _now() -> str:
    import datetime as dt
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
