"""scripts/lag_probe.py ujung ke ujung terhadap engine asli (sumber mock).

Alat uji yang tidak pernah diuji adalah sumber kesimpulan palsu: kalau probe
salah membaca `at` atau gagal handshake, "engine segar" bisa berarti "probe tidak
menerima apa-apa".
"""

from __future__ import annotations

import csv
import dataclasses
import socket
import threading
import time

import pytest

from engine.config import load_config
from engine.runtime.service import EngineRuntime, RuntimeOptions

KEY = "kunci-uji-0123456789abcdef-0123456789"


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.mark.parametrize("auth_key", [None, KEY])
def test_probe_mengukur_engine_dan_menyimpulkan(tmp_path, monkeypatch, auth_key):
    import importlib.util
    spec = importlib.util.spec_from_file_location("lag_probe", "scripts/lag_probe.py")
    lag_probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lag_probe)

    port = _free_port()
    config = dataclasses.replace(load_config(), source_type="mock", auto_warmup=False, strict_mode=True)
    runtime = EngineRuntime(config=config, options=RuntimeOptions(
        tcp=("127.0.0.1", port), health_interval_seconds=0.5, view_fps=5.0, auth_key=auth_key,
        target_fps=10.0,
    ))
    runtime.listen()
    threading.Thread(target=runtime.api.serve_forever, daemon=True).start()
    time.sleep(0.2)
    try:
        out = tmp_path / "probe.csv"
        lines = lag_probe.run("127.0.0.1", port, [("cam01", "mock")], 4.0, out, auth_key)
        text = "\n".join(lines)
        assert "== cam01" in text and "KESIMPULAN" in text, text
        with out.open(encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        views = [r for r in rows if r["source"] == "view" and r["camera_id"] == "cam01"]
        assert len(views) >= 2, "probe wajib menerima view.frame dari engine"
        # Sumber mock berjalan jauh lebih cepat dari real-time: probe wajib
        # menolak menyimpulkan apa pun, bukan berkata "engine segar".
        assert "TIDAK VALID" in text, text
        assert any(r["source"] == "event" and "camera.online" in r["note"] for r in rows)
    finally:
        runtime.close()


def test_probe_ditolak_tanpa_kunci_bila_engine_meminta(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("lag_probe", "scripts/lag_probe.py")
    lag_probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lag_probe)

    port = _free_port()
    config = dataclasses.replace(load_config(), source_type="mock", auto_warmup=False)
    runtime = EngineRuntime(config=config, options=RuntimeOptions(tcp=("127.0.0.1", port), auth_key=KEY))
    runtime.listen()
    threading.Thread(target=runtime.api.serve_forever, daemon=True).start()
    time.sleep(0.2)
    try:
        with pytest.raises(SystemExit, match="ENGINE_SHARED_KEY"):
            lag_probe.connect("127.0.0.1", port, None)
    finally:
        runtime.close()


def test_kesimpulan_membedakan_delay_bertambah_dan_tetap():
    import importlib.util
    spec = importlib.util.spec_from_file_location("lag_probe", "scripts/lag_probe.py")
    lag_probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lag_probe)

    def rows(age_of):
        return [{"camera_id": "cam01", "source": "view", "elapsed_s": float(t),
                 "frame_age_s": age_of(t), "lag_s": "", "fps": "", "note": ""} for t in range(300)]

    growing = "\n".join(lag_probe.summarize(rows(lambda t: 0.3 + t * 0.05), 300))
    fresh = "\n".join(lag_probe.summarize(rows(lambda t: 0.4), 300))
    stuck = "\n".join(lag_probe.summarize(rows(lambda t: 3.2), 300))
    future = "\n".join(lag_probe.summarize(rows(lambda t: -40.0 - t), 300))
    assert "BERTAMBAH" in growing
    assert "SEGAR" in fresh
    assert "TETAP tapi besar" in stuck
    assert "TIDAK VALID" in future and "SEGAR" not in future
