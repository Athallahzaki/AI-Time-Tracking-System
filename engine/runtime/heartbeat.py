"""Berkas detak untuk watchdog luar (paket ea-r6, dokumen 12 §2.4, dokumen 04 §14.6).

Watchdog (`deploy/laptop/engine-watchdog.ps1`) hanya bisa melihat dua hal dari
luar: proses masih ada, dan berkas ini masih diperbarui. Proses yang hidup tapi
tidak lagi memperbarui berkas = macet (GIL terkunci, CUDA menggantung, thread
ticker mati), dan itu tidak bisa dibedakan dari "sibuk" tanpa detak.

Yang menulis adalah ticker runtime (thread yang juga memancarkan snapshot dan
engine.health), bukan thread terpisah: detak dari thread yang tidak ikut macet
hanya membuktikan bahwa thread itu sendiri hidup.

Ditulis atomik (berkas sementara + `os.replace`), supaya watchdog tidak pernah
membaca JSON setengah jadi. Isinya juga memuat jumlah frame per kamera, untuk
diagnosis di log; keputusan "macet" watchdog hanya memakai umur berkas.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULT_INTERVAL_SECONDS = 5.0


def write_heartbeat(path: str, payload: Dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    os.replace(temporary, target)


def read_heartbeat(path: str) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def heartbeat_age(path: str, now: Optional[float] = None) -> Optional[float]:
    """Detik sejak detak terakhir (dari isi berkas), None bila tidak ada/rusak."""
    data = read_heartbeat(path)
    if not data or not isinstance(data.get("ts"), (int, float)):
        return None
    return (time.time() if now is None else now) - float(data["ts"])


class Heartbeat:
    """Penulis berkala; `beat(now, cameras)` dipanggil ticker setiap putaran."""

    def __init__(self, path: str, interval_seconds: float = DEFAULT_INTERVAL_SECONDS) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval detak harus > 0")
        self.path = path
        self._interval = float(interval_seconds)
        self._last = float("-inf")
        self.failures = 0

    def beat(self, now: float, cameras: Dict[str, Any]) -> bool:
        if now - self._last < self._interval:
            return False
        self._last = now
        try:
            write_heartbeat(self.path, {"pid": os.getpid(), "ts": now, "cameras": cameras})
        except OSError:
            # Disk penuh/berkas terkunci antivirus: jangan matikan ticker.
            # Watchdog akan melihat detak basi dan bertindak; itu memang benar.
            self.failures += 1
            return False
        return True
