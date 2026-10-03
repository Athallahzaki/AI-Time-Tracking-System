"""Engine harus bisa dihentikan: Ctrl+C sekali rapi, dua kali paksa, dan tidak
pernah menggantung selamanya (laporan 3 Okt, Windows)."""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import threading
import time

import pytest

from engine.runtime.__main__ import _Stopper


def test_pertama_rapi_kedua_paksa():
    closed = threading.Event()
    exits = []
    stopper = _Stopper(close=closed.set, grace=5.0, exit_fn=exits.append)
    stopper.request("uji")
    assert closed.wait(1.0), "permintaan pertama menjalankan close() rapi"
    assert exits == []
    stopper.request("uji lagi")
    assert exits == [130]


def test_close_yang_macet_dipaksa_oleh_penjaga_waktu():
    exits = []
    stuck = threading.Event()
    stopper = _Stopper(close=stuck.wait, grace=0.3, exit_fn=exits.append)
    stopper.request("uji")
    deadline = time.time() + 3.0
    while not exits and time.time() < deadline:
        time.sleep(0.05)
    stuck.set()
    assert exits == [1]


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.mark.skipif(os.name == "nt", reason="SIGINT ke subprocess berbeda di Windows")
def test_proses_engine_keluar_setelah_sigint(tmp_path):
    port = _free_port()
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([os.getcwd(), os.environ.get("PYTHONPATH", "")]))
    process = subprocess.Popen(
        [sys.executable, "-m", "engine.runtime", "--tcp", f"127.0.0.1:{port}",
         "--outbox", str(tmp_path / "outbox.sqlite3"), "--quiet"],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
    )
    try:
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
                break
            except OSError:
                if process.poll() is not None:
                    pytest.fail(process.stderr.read().decode(errors="replace"))
                time.sleep(0.2)
        process.send_signal(signal.SIGINT)
        code = process.wait(timeout=15)
        assert code == 0, process.stderr.read().decode(errors="replace")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        process.stdout.close()
        process.stderr.close()
