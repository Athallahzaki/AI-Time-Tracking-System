"""Berkas detak dan berkas stop untuk watchdog Windows (paket ea-r6).

Watchdog sendiri (`deploy/laptop/engine-watchdog.ps1`) diuji manual di laptop;
di sini dikunci sisi engine yang menjadi tumpuannya.
"""

from __future__ import annotations

import dataclasses
import json
import os
import threading
import time

import pytest

from engine.config import load_config
from engine.runtime import EngineRuntime, RuntimeOptions
from engine.runtime.__main__ import build_parser
from engine.runtime.heartbeat import Heartbeat, heartbeat_age, read_heartbeat, write_heartbeat


def test_detak_ditulis_atomik_dan_menurut_interval(tmp_path):
    path = tmp_path / "hb" / "heartbeat.json"
    beat = Heartbeat(str(path), interval_seconds=5.0)
    assert beat.beat(100.0, {"r1": {"state": "online", "frames": 3}})
    assert not beat.beat(103.0, {})              # belum 5 dtk
    assert beat.beat(105.0, {})
    data = read_heartbeat(str(path))
    assert data["ts"] == 105.0 and data["pid"] == os.getpid()
    assert heartbeat_age(str(path), now=112.0) == pytest.approx(7.0)
    assert not (tmp_path / "hb" / "heartbeat.json.tmp").exists()


def test_detak_rusak_atau_hilang_dibaca_none(tmp_path):
    assert heartbeat_age(str(tmp_path / "tidak-ada.json")) is None
    broken = tmp_path / "rusak.json"
    broken.write_text("{setengah", encoding="utf-8")
    assert heartbeat_age(str(broken)) is None


def test_gagal_menulis_tidak_mematikan_ticker(tmp_path):
    folder = tmp_path / "bukan-folder"
    folder.write_text("x", encoding="utf-8")     # berkas, bukan folder: mkdir gagal
    beat = Heartbeat(str(folder / "heartbeat.json"), interval_seconds=1.0)
    assert not beat.beat(10.0, {})
    assert beat.failures == 1


def test_interval_detak_harus_positif():
    with pytest.raises(ValueError):
        Heartbeat("x.json", interval_seconds=0)


def test_opsi_cli_default_mati_dan_bisa_dari_env(monkeypatch):
    args = build_parser().parse_args([])
    assert args.heartbeat_file is None and args.stop_file is None
    monkeypatch.setenv("ENGINE_HEARTBEAT_FILE", "logs/engine/heartbeat.json")
    monkeypatch.setenv("ENGINE_STOP_FILE", "logs/engine/engine.stop")
    args = build_parser().parse_args(["--heartbeat-seconds", "2"])
    assert args.heartbeat_file == "logs/engine/heartbeat.json"
    assert args.stop_file == "logs/engine/engine.stop"
    assert args.heartbeat_seconds == 2.0


def _runtime(tmp_path, **options):
    config = dataclasses.replace(load_config(), source_type="mock", auto_warmup=False)
    return EngineRuntime(config=config, options=RuntimeOptions(tcp=("127.0.0.1", 0), **options))


def _wait(predicate, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_ticker_runtime_menulis_detak(tmp_path):
    path = tmp_path / "heartbeat.json"
    runtime = _runtime(tmp_path, heartbeat_path=str(path), heartbeat_interval_seconds=0.5)
    runtime.listen()
    try:
        assert _wait(path.exists), "ticker tidak menulis detak"
        first = read_heartbeat(str(path))["ts"]
        assert _wait(lambda: read_heartbeat(str(path))["ts"] > first), "detak tidak diperbarui"
        assert json.loads(path.read_text(encoding="utf-8"))["cameras"] == {}
    finally:
        runtime.close()


def test_tanpa_opsi_tidak_ada_berkas_yang_ditulis(tmp_path):
    runtime = _runtime(tmp_path)
    runtime.listen()
    try:
        time.sleep(1.2)
    finally:
        runtime.close()
    assert list(tmp_path.iterdir()) == []


def test_berkas_stop_memanggil_jalur_berhenti_sekali(tmp_path):
    stop = tmp_path / "engine.stop"
    runtime = _runtime(tmp_path, stop_file=str(stop))
    calls = []
    runtime.on_stop_file = lambda: calls.append(time.time())
    runtime.listen()
    try:
        time.sleep(0.8)
        assert calls == []
        stop.write_text("", encoding="utf-8")
        assert _wait(lambda: calls), "berkas stop tidak terlihat"
        assert not stop.exists(), "berkas stop harus dihapus setelah dibaca"
        stop.write_text("", encoding="utf-8")
        time.sleep(1.2)
        assert len(calls) == 1
    finally:
        runtime.close()


def test_berkas_stop_lama_dihapus_saat_start(tmp_path):
    stop = tmp_path / "engine.stop"
    stop.write_text("", encoding="utf-8")
    runtime = _runtime(tmp_path, stop_file=str(stop))
    calls = []
    runtime.on_stop_file = lambda: calls.append(1)
    runtime.listen()
    try:
        assert not stop.exists()
        time.sleep(1.2)
        assert calls == []
    finally:
        runtime.close()


def test_tanpa_callback_berkas_stop_menutup_runtime(tmp_path):
    stop = tmp_path / "engine.stop"
    runtime = _runtime(tmp_path, stop_file=str(stop))
    runtime.listen()
    stop.write_text("", encoding="utf-8")
    assert _wait(lambda: runtime._closed.is_set()), "runtime tidak berhenti"
    runtime.close()
