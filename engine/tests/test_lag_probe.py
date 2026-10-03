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


def test_event_putar_ulang_dari_outbox_tidak_ikut_dihitung(tmp_path):
    """Probe mengirim last_event_seq=0, jadi engine memutar ulang outbox. Health
    dari run sebelumnya pernah ikut terhitung dan mengacaukan ringkasan."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("lag_probe", "scripts/lag_probe.py")
    lag_probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lag_probe)

    port = _free_port()
    config = dataclasses.replace(load_config(), source_type="mock", auto_warmup=False)
    runtime = EngineRuntime(config=config, options=RuntimeOptions(
        tcp=("127.0.0.1", port), health_interval_seconds=0.5, view_fps=5.0))
    # Health "lama" di outbox, seolah dari run sebelumnya.
    runtime.api.emit_event({"type": "engine.health", "v": 1, "ts": "2026-01-01T00:00:00.000Z",
                            "models_loaded": False, "queue_depth": 0, "drop_rate": 0.0,
                            "cameras": {"cam01": "online"},
                            "camera_metrics": {"cam01": {"effective_fps": 99.0, "lag_seconds": 9.0}}})
    runtime.listen()
    threading.Thread(target=runtime.api.serve_forever, daemon=True).start()
    time.sleep(0.2)
    try:
        out = tmp_path / "probe.csv"
        lines = lag_probe.run("127.0.0.1", port, [("cam01", "mock")], 2.0, out, None)
        with out.open(encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        assert not any(r["fps"] == "99.0" for r in rows), "health lama ikut tercatat"
        assert any("putar ulang" in line for line in lines)
    finally:
        runtime.close()


def _load_probe():
    import importlib.util
    spec = importlib.util.spec_from_file_location("lag_probe", "scripts/lag_probe.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_engine_yang_lambat_mulai_tidak_membuat_ringkasan_crash(tmp_path, capsys):
    """Laporan lapangan 3 Okt (GTX 1060): view.frame pertama baru datang setelah
    lebih dari 60 dtk (muat model + warmup CUDA), jendela "awal" kosong, dan
    probe crash dengan `NoneType.__format__` setelah 5 menit menunggu."""
    lag_probe = _load_probe()
    rows = [{"camera_id": "cam01", "source": "view", "elapsed_s": float(t), "frame_age_s": 0.5,
             "lag_s": "", "fps": "", "note": ""} for t in range(90, 300)]
    text = "\n".join(lag_probe.summarize(rows, 300))
    assert "view.frame pertama pada detik 90" in text and "SEGAR" in text

    # CSV yang sudah tersimpan bisa diringkas ulang tanpa mengulang uji.
    path = tmp_path / "lag.csv"
    fields = ["wall_t", "elapsed_s", "camera_id", "source", "frame_age_s", "lag_s", "fps", "dropped",
              "drift_s", "note"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for t in range(90, 300):
            writer.writerow({"wall_t": 1000 + t, "elapsed_s": t, "camera_id": "cam01", "source": "view",
                             "frame_age_s": 0.5, "lag_s": "", "fps": "", "dropped": "", "drift_s": "",
                             "note": ""})
        writer.writerow({"wall_t": 1300, "elapsed_s": 300, "camera_id": "cam01", "source": "health",
                         "frame_age_s": "", "lag_s": 0.1, "fps": 7.5, "dropped": 3, "drift_s": -0.04,
                         "note": "online"})
    assert lag_probe.main(["--summarize", str(path)]) == 0
    out = capsys.readouterr().out
    assert "SEGAR" in out and "fps analisis: median 7.5" in out and "-0.04" in out


def test_median_segar_tapi_lonjakan_tidak_lulus():
    """Uji 4060 (3 Okt): median 0,5 dtk, tetapi umur 6 dtk dan fps jatuh ke 2,3."""
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("lag_probe_w", Path("scripts/lag_probe.py"))
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    rows = []
    for i in range(120):
        t = float(i)
        age = 6.0 if 60 <= i < 66 else 0.5
        rows.append({"elapsed_s": t, "camera_id": "cam01", "source": "view", "frame_age_s": age,
                     "lag_s": "", "fps": "", "drift_s": "", "note": ""})
        if i % 2 == 0:
            rows.append({"elapsed_s": t, "camera_id": "cam01", "source": "health", "frame_age_s": "",
                         "lag_s": 0.1, "fps": 2.5 if 40 <= i < 80 else 8.0,
                         "drift_s": 1.8 if i == 64 else -0.05, "note": ""})
    text = "\n".join(probe.summarize(rows, 120.0))
    assert "TIDAK STABIL" in text
    assert "terburuk 6.00" in text and "fps turun ke 2.5" in text and "POSITIF" in text
