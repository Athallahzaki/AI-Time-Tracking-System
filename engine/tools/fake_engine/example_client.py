"""Klien backend minimal — contoh, sekaligus uji asap untuk server.

Enam puluh baris, tanpa library, dan ia menunjukkan seluruh jabat tangan:
`hello` dengan `last_event_seq`, membaca `hello_ack`, menangani `replay_gap`
sebagai lubang data, lalu menerima event. Backend boleh menyalin ini apa
adanya sebagai titik awal `engine_link/`.

    # terminal 1
    python -m engine.tools.fake_engine --scenario berbalik-lama --socket /tmp/e.sock --speed 60
    # terminal 2
    python -m engine.tools.fake_engine.example_client /tmp/e.sock

Jalankan sekali, catat `seq` terakhir, lalu jalankan lagi dengan
`--last-seq <n>`: engine mengulang dari nomor berikutnya. Itu perbedaan antara
deploy backend yang berisiko dan deploy yang tidak perlu dipikirkan.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
from typing import Optional


def run(address: str, last_seq: int = 0, limit: Optional[int] = None) -> int:
    if ":" in address:
        host, _, port = address.rpartition(":")
        connection = socket.create_connection((host or "127.0.0.1", int(port)), timeout=30)
    else:
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.settimeout(30)
        connection.connect(address)

    stream = connection.makefile("r", encoding="utf-8")

    connection.sendall((json.dumps({
        "type": "hello", "v": 1, "ts": "1970-01-01T00:00:00.000Z",
        "protocol_version": 1, "client": "example-client/0.1",
        "last_event_seq": last_seq,
    }) + "\n").encode())

    seen = 0
    highest = last_seq

    for line in stream:
        line = line.strip()
        if not line:
            continue
        message = json.loads(line)
        kind = message.get("type")

        if kind == "hello_ack":
            print(f"hello_ack: engine {message['engine_version']}, "
                  f"outbox tertua seq={message['oldest_available_seq']}")
            continue

        if kind == "replay_gap":
            # Lubang data, bukan "tidak ada kejadian". Backend yang salah di
            # sini akan menandai orang absen untuk periode yang tidak pernah
            # diamati siapa pun.
            print(f"!! LUBANG DATA: seq {message['from_seq']}..{message['to_seq']} "
                  "tidak bisa diulang. Jangan perlakukan sebagai ketidakhadiran.")
            continue

        if "seq" in message:
            if message["seq"] != highest + 1 and highest:
                print(f"!! seq melompat: {highest} -> {message['seq']}")
            highest = message["seq"]

        seen += 1
        if kind in {"presence.interval", "track.identified", "track.ended",
                    "camera.online", "camera.failed", "replay_gap"}:
            print(f"  seq={message.get('seq', '-'):>4} {kind}")

        if limit and seen >= limit:
            break

    print(f"selesai: {seen} pesan, seq terakhir {highest}")
    connection.close()
    return highest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("address", help="path unix socket atau host:port")
    parser.add_argument("--last-seq", type=int, default=0)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)
    run(args.address, args.last_seq, args.limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
