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
    parser.add_argument("--quiet", action="store_true")
    return parser


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

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
            outbox_path=args.outbox,
        )
    )

    def _stop(signum, _frame):
        # Cameras close their open intervals with `engine_shutdown` on the way
        # out (§4.2). Killing the process instead leaves every presence open and
        # the backend carrying people who never left.
        logging.getLogger("engine.runtime").info("sinyal %s: berhenti rapi", signum)
        runtime.close()

    for name in ("SIGINT", "SIGTERM"):
        handler = getattr(signal, name, None)
        if handler is not None:
            try:
                signal.signal(handler, _stop)
            except (ValueError, OSError):
                pass

    print(
        "engine siap. Menunggu `set_cameras` dari backend — kamera adalah "
        "milik backend untuk dideklarasikan (§2.2), jadi tidak ada stream yang "
        "dibuka sebelum pesan itu datang.",
        file=sys.stderr,
    )
    runtime.serve()
    return 0


if __name__ == "__main__":
    sys.exit(main())
