"""
`python -m engine.runtime` — the real engine, on a socket.

    # what the backend connects to today (services/engine_client.py)
    python -m engine.runtime --tcp 127.0.0.1:8765

    # one machine, where the platform has Unix sockets
    python -m engine.runtime --socket /tmp/engine.sock

TCP is the default because the backend's client dials `127.0.0.1:8765`, and
because Windows has no `AF_UNIX` at all — half this team would otherwise be
unable to run the thing they are integrating with. The contract allows either
(§1).
"""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
import signal
import sys
import threading
from typing import Optional

from .service import EngineRuntime, RuntimeOptions

_DEFAULT_OUTBOX = Path(__file__).resolve().parents[1] / "data" / "outbox.sqlite3"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="engine.runtime",
        description="Run the real engine and serve the NDJSON protocol.",
    )
    parser.add_argument(
        "--tcp", default="127.0.0.1:8765",
        help="host:port to listen on (default: what the backend client dials)",
    )
    parser.add_argument(
        "--socket", default=None,
        help="Unix socket path instead of TCP. Not available on Windows.",
    )
    parser.add_argument("--config", default=None, help="engine config YAML")
    parser.add_argument(
        "--view-fps", type=float, default=10.0,
        help="overlay frames per second per camera, best-effort. 0 disables.",
    )
    parser.add_argument(
        "--snapshot-seconds", type=float, default=10.0,
        help="how often the whole live picture is restated (§4.5)",
    )
    parser.add_argument(
        "--outbox",
        default=os.environ.get("ENGINE_OUTBOX_PATH", str(_DEFAULT_OUTBOX)),
        help="berkas SQLite outbox durabel (default engine/data/outbox.sqlite3). "
             "Jangan dihapus saat backend masih menyimpan last_event_seq.",
    )
    parser.add_argument(
        "--target-fps", type=float,
        default=float(os.environ["ENGINE_TARGET_FPS"]) if os.environ.get("ENGINE_TARGET_FPS") else None,
        help="batasi frame yang dianalisis per detik per kamera (mis. 10-12). "
             "Frame lain tetap di-decode tapi tidak masuk detector/tracker.",
    )
    parser.add_argument(
        "--loop-files", action="store_true",
        default=os.environ.get("ENGINE_LOOP_FILES", "").lower() in ("1", "true", "yes"),
        help="ulang video file lokal dari awal saat habis (demo). Stream "
             "jaringan tidak terpengaruh.",
    )
    parser.add_argument(
        "--health-seconds", type=float, default=30.0,
        help="interval engine.health (default 30). Turunkan ke 2-5 untuk uji lag.",
    )
    parser.add_argument(
        "--heartbeat-file", default=os.environ.get("ENGINE_HEARTBEAT_FILE") or None,
        help="tulis berkas detak JSON berkala untuk watchdog luar "
             "(deploy/laptop/engine-watchdog.ps1). Default mati.",
    )
    parser.add_argument(
        "--heartbeat-seconds", type=float, default=5.0,
        help="interval berkas detak (default 5)",
    )
    parser.add_argument(
        "--stop-file", default=os.environ.get("ENGINE_STOP_FILE") or None,
        help="bila berkas ini muncul, engine berhenti rapi (cara watchdog Windows "
             "menghentikan engine tanpa SIGTERM). Default mati.",
    )
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument(
        "--allow-power-throttling", action="store_true",
        help="Windows: biarkan EcoQoS/power throttling (default: dimatikan untuk proses engine; "
             "lihat runtime/winpower.py)",
    )
    return parser


def _shared_key(tcp) -> Optional[str]:
    """Kunci handshake dari env ENGINE_SHARED_KEY (P3). Sengaja bukan argumen
    CLI: argumen proses bisa dibaca siapa saja lewat `ps`."""
    key = os.environ.get("ENGINE_SHARED_KEY") or None
    log = logging.getLogger("engine.runtime")
    if key is None and tcp is not None and tcp[0] not in ("127.0.0.1", "localhost", "::1"):
        log.warning(
            "engine mendengarkan di %s TANPA autentikasi handshake. Host mana pun di "
            "jaringan bisa membaca event dan menendang backend (P3). Isi ENGINE_SHARED_KEY.",
            tcp[0],
        )
    return key


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    if not args.allow_power_throttling:
        from .winpower import disable_power_throttling

        logging.getLogger("engine.runtime").info("%s", disable_power_throttling())

    tcp = None
    if not args.socket:
        host, _, port = args.tcp.rpartition(":")
        if not host or not port.isdigit():
            print(f"--tcp harus host:port, dapat {args.tcp!r}", file=sys.stderr)
            return 2
        tcp = (host, int(port))

    runtime = EngineRuntime(
        options=RuntimeOptions(
            config_path=args.config,
            tcp=tcp,
            socket_path=args.socket,
            view_fps=args.view_fps,
            snapshot_interval_seconds=args.snapshot_seconds,
            health_interval_seconds=args.health_seconds,
            outbox_path=args.outbox,
            target_fps=args.target_fps,
            loop_files=args.loop_files,
            auth_key=_shared_key(tcp),
            heartbeat_path=args.heartbeat_file,
            heartbeat_interval_seconds=args.heartbeat_seconds,
            stop_file=args.stop_file,
        )
    )

    stopper = _Stopper(runtime.close)
    runtime.on_stop_file = lambda: stopper.request("berkas stop")

    def _on_signal(signum, _frame):
        stopper.request(f"sinyal {signum}")

    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        handler = getattr(signal, name, None)
        if handler is not None:
            try:
                signal.signal(handler, _on_signal)
            except (ValueError, OSError):
                pass
    _watch_stdin(stopper)

    print(
        "engine siap. Menunggu `set_cameras` dari backend — kamera adalah "
        "milik backend untuk dideklarasikan (§2.2), jadi tidak ada stream yang "
        "dibuka sebelum pesan itu datang. Berhenti: Ctrl+C, atau ketik q lalu Enter.",
        file=sys.stderr,
    )
    runtime.serve()
    return 0


SHUTDOWN_GRACE_SECONDS = 20.0   # batas berhenti rapi sebelum dipaksa
STDIN_COMMANDS = {"q", "quit", "exit", "stop"}


class _Stopper:
    """Satu jalur berhenti untuk Ctrl+C, SIGTERM, dan perintah `q` di terminal.

    Pertama kali: berhenti rapi di thread terpisah (kamera menutup interval
    dengan `engine_shutdown`, §4.2), plus penjaga waktu yang memaksa keluar bila
    rapi-nya macet -- mis. thread kamera masih di tengah memuat model (±55 dtk
    di GTX 1060) atau terjebak di panggilan CUDA/FFmpeg yang tidak bisa diputus.
    Kedua kali: keluar paksa saat itu juga.
    """

    def __init__(self, close, grace: float = SHUTDOWN_GRACE_SECONDS, exit_fn=None) -> None:
        self._close = close
        self._grace = grace
        self._exit = exit_fn or os._exit
        self._lock = threading.Lock()
        self.requests = 0

    def request(self, reason: str) -> None:
        with self._lock:
            self.requests += 1
            first = self.requests == 1
        if not first:
            print("berhenti paksa.", file=sys.stderr, flush=True)
            self._exit(130)
            return
        print(f"menghentikan engine dengan rapi ({reason}); Ctrl+C sekali lagi atau tunggu "
              f"{self._grace:.0f} dtk untuk paksa...", file=sys.stderr, flush=True)
        logging.getLogger("engine.runtime").info("%s: berhenti rapi", reason)
        # Di thread terpisah: handler sinyal jalan di thread utama, dan close()
        # menunggu kamera selesai. Ctrl+C kedua harus tetap bisa diterima.
        threading.Thread(target=self._close, name="engine-shutdown", daemon=True).start()
        threading.Thread(target=self._watchdog, name="engine-shutdown-watchdog", daemon=True).start()

    def _watchdog(self) -> None:
        threading.Event().wait(self._grace)
        print(f"berhenti rapi melewati {self._grace:.0f} dtk; keluar paksa.", file=sys.stderr, flush=True)
        self._exit(1)


def _watch_stdin(stopper: _Stopper) -> None:
    """Ketik `q` lalu Enter untuk berhenti -- cadangan bila Ctrl+C tertelan.

    Di Windows, Ctrl+C bisa tidak sampai ke Python: pustaka native (CUDA, MKL)
    memasang penangan konsol sendiri, atau jendela konsol sedang dalam mode
    seleksi (QuickEdit) sehingga proses membeku saat menulis log.
    """
    stream = sys.stdin
    try:
        interactive = stream is not None and stream.isatty()
    except (ValueError, OSError):
        interactive = False
    if not interactive:
        return

    def _loop() -> None:
        for line in stream:
            if line.strip().lower() in STDIN_COMMANDS:
                stopper.request("perintah terminal")

    threading.Thread(target=_loop, name="engine-stdin", daemon=True).start()


def _exit_now(code: int) -> None:
    """Keluar tanpa finalisasi interpreter.

    Thread daemon yang masih berada di dalam kode native (PyAV menunggu RTSP,
    CUDA, onnxruntime) bisa membuat finalisasi Python macet di Windows: engine
    sudah berhenti rapi tetapi prosesnya tidak pernah selesai, dan Ctrl+C tidak
    lagi diproses karena handler sinyal tidak jalan selama finalisasi.
    """
    logging.shutdown()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:  # noqa: BLE001
            pass
    os._exit(code)


if __name__ == "__main__":
    _exit_now(main())
