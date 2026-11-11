"""Paket H: sisi engine kontrak debug sementara (runtime/debug_bridge.py)."""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path

import numpy as np
import pytest

# CI engine memasang jsonschema (engine.yml); tanpa itu berkas ini dilewati.
Draft202012Validator = pytest.importorskip("jsonschema").Draft202012Validator

from engine.config.schema import DebugConfig
from engine.runtime.debug_bridge import DebugBridge

SCHEMA = Draft202012Validator(json.loads(
    (Path(__file__).resolve().parents[2] / "contracts" / "schema" / "debug.schema.json").read_text(encoding="utf-8")))


class _Api:
    def __init__(self) -> None:
        self.generation = 1
        self.views = []

    def emit_view(self, message) -> bool:
        self.views.append(message)
        return True


def _sah(message) -> dict:
    if message["type"] != "ack":
        assert list(SCHEMA.iter_errors(message)) == [], message["type"]
    return message


def _bridge(enabled: bool = True, capacity: int = 3, label=None):
    api = _Api()
    bridge = DebugBridge(api, enabled, capacity, label_of=label)
    return api, bridge


def _crop(value: int) -> np.ndarray:
    return np.full((200, 60, 3), value, dtype=np.uint8)


def test_mati_di_engine_menolak_semuanya():
    api, bridge = _bridge(enabled=False)
    reply = bridge.on_subscribe({"type": "debug.subscribe", "enabled": True})
    assert reply["accepted"] is False and "debug mati" in reply["reason"]
    assert bridge.on_crop_list({"request_id": "r1"})["accepted"] is False
    assert bridge.on_crop_request({"request_id": "r1", "track_uuid": "tr_a"})["accepted"] is False
    assert DebugConfig().enabled is False


def test_tanpa_langganan_tidak_ada_yang_keluar():
    api, bridge = _bridge()
    bridge.remember("cam01", "tr_a", 10.0, _crop(50))
    assert bridge.on_crop_request({"request_id": "r1", "track_uuid": "tr_a"})["accepted"] is False
    bridge.forward_log(logging.LogRecord("engine", logging.ERROR, "", 0, "rahasia", (), None))
    assert api.views == []


def test_daftar_dan_gambar_crop_setelah_berlangganan():
    api, bridge = _bridge(label=lambda uuid: ("ANON-k3", "reid") if uuid == "tr_b" else None)
    assert bridge.on_subscribe({"type": "debug.subscribe", "enabled": True})["accepted"] is True
    bridge.remember("cam01", "tr_a", 10.0, _crop(50))
    bridge.remember("cam02", "tr_b", 11.0, _crop(200))

    listed = _sah(bridge.on_crop_list({"request_id": "r1"}))
    assert [(c["track_uuid"], c["person_id"]) for c in listed["crops"]] == [("tr_b", "ANON-k3"), ("tr_a", None)]
    assert "jpeg_b64" not in json.dumps(listed)                       # daftar tidak membawa gambar

    crop = _sah(bridge.on_crop_request({"request_id": "r2", "track_uuid": "tr_b"}))
    assert (crop["found"], crop["camera_id"], crop["width"], crop["height"]) == (True, "cam02", 60, 200)
    import cv2
    decoded = cv2.imdecode(np.frombuffer(base64.b64decode(crop["jpeg_b64"]), np.uint8), cv2.IMREAD_COLOR)
    assert decoded.shape == (200, 60, 3) and abs(int(decoded.mean()) - 200) <= 3

    missing = _sah(bridge.on_crop_request({"request_id": "r3", "track_uuid": "tr_tidak_ada"}))
    assert missing["found"] is False and "jpeg_b64" not in missing


def test_cache_crop_berbatas_dan_satu_per_track():
    api, bridge = _bridge(capacity=3)
    bridge.on_subscribe({"enabled": True})
    for index in range(5):
        bridge.remember("cam01", f"tr_{index}", float(index), _crop(index))
    bridge.remember("cam01", "tr_3", 9.0, _crop(99))                  # track yang sama: diganti, bukan ditambah
    listed = bridge.on_crop_list({"request_id": "r"})["crops"]
    assert [c["track_uuid"] for c in listed] == ["tr_3", "tr_4", "tr_2"]


def test_koneksi_baru_tidak_mewarisi_langganan():
    api, bridge = _bridge()
    bridge.on_subscribe({"enabled": True})
    bridge.remember("cam01", "tr_a", 10.0, _crop(50))
    api.generation += 1                                               # backend lain / lama tersambung
    assert bridge.subscribed is False
    assert bridge.on_crop_request({"request_id": "r", "track_uuid": "tr_a"})["accepted"] is False
    bridge.forward_log(logging.LogRecord("engine", logging.ERROR, "", 0, "x", (), None))
    assert api.views == []


def test_log_warning_diteruskan_dan_berhenti_saat_dimatikan():
    api, bridge = _bridge()
    bridge.on_subscribe({"enabled": True})
    log = logging.getLogger("engine.uji.debug")
    try:
        log.info("biasa saja")
        log.warning("[cam01] masih gagal dibuka: %s", "404")
        assert [(_sah(v)["level"], v["message"]) for v in api.views] == [("WARNING", "[cam01] masih gagal dibuka: 404")]
        bridge.on_subscribe({"enabled": False})
        log.error("sesudah dimatikan")
        assert len(api.views) == 1
    finally:
        bridge.close()


def test_config_debug_dimuat_dan_divalidasi(tmp_path):
    from engine.config import load_config
    path = tmp_path / "engine.yaml"
    path.write_text('core:\n  source_type: "mock"\ndebug:\n  enabled: true\n  crop_cache_tracks: 50\n', encoding="utf-8")
    config = load_config(str(path))
    assert (config.debug.enabled, config.debug.crop_cache_tracks) == (True, 50)
    with pytest.raises(ValueError):
        DebugConfig(crop_cache_tracks=0)
