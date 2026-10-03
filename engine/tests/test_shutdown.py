"""Engine harus bisa dihentikan saat sedang menunggu backend (Ctrl+C di Windows).

Sebelumnya serve_forever() memblok di accept() tanpa batas waktu. Di Windows
handler Ctrl+C tidak pernah jalan sampai ada klien tersambung.
"""

from __future__ import annotations

import threading
import time

from engine.config import load_config
from engine.runtime.service import EngineRuntime, RuntimeOptions


def _runtime(tmp_path):
    return EngineRuntime(
        config=load_config("engine/config/default_config.yaml"),
        options=RuntimeOptions(tcp=("127.0.0.1", 0)),
    )


def test_serve_berhenti_cepat_tanpa_klien(tmp_path):
    runtime = _runtime(tmp_path)
    done = threading.Event()

    def serve():
        runtime.serve()
        done.set()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    time.sleep(0.3)                      # sedang menunggu di accept(), belum ada klien
    started = time.monotonic()
    threading.Thread(target=runtime.close, daemon=True).start()   # seperti handler Ctrl+C
    assert done.wait(3.0), "serve() tidak kembali setelah close() saat menunggu klien"
    assert time.monotonic() - started < 2.0


def test_close_dari_dua_thread_menunggu_yang_pertama(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path)
    runtime.listen()
    order = []

    class SlowCamera:
        def request_stop(self):
            order.append("request")

        def stop(self):
            time.sleep(0.5)
            order.append("stopped")

    runtime._cameras["cam01"] = SlowCamera()
    first = threading.Thread(target=runtime.close)
    first.start()
    time.sleep(0.1)
    runtime.close()                      # pemanggil kedua (akhir serve()) harus menunggu
    assert order == ["request", "stopped"], "pemanggil kedua kembali sebelum kamera selesai ditutup"
    first.join(2.0)
