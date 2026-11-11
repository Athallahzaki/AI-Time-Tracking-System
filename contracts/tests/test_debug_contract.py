"""Kontrak debug SEMENTARA (contracts/schema/debug.schema.json, Paket H).

Tes ini menjaga tiga janji: kontrak debug terpisah dari kontrak produksi, tidak
pernah durabel, dan benar-benar sementara.
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
DEBUG = json.loads((ROOT / "schema" / "debug.schema.json").read_text(encoding="utf-8"))
MAIN = json.loads((ROOT / "schema" / "engine_protocol.schema.json").read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(DEBUG)

# Setelah tanggal ini kontrak debug harus DIHAPUS (skema, engine/runtime/debug_bridge.py,
# backend/services/debug_service.py bagian engine) atau diangkat menjadi kontrak resmi
# lewat keputusan EA. Memundurkan tanggal ini tanpa keputusan = melanggar janji "sementara".
KEDALUWARSA = datetime.date(2027, 2, 28)

TS = "2026-11-11T12:00:00.000Z"
SAH = [
    {"type": "debug.subscribe", "v": 1, "ts": TS, "enabled": True},
    {"type": "debug.log", "v": 1, "ts": TS, "channel": "view", "level": "WARNING",
     "logger": "engine.runtime.camera", "message": "[cam01] masih gagal dibuka"},
    {"type": "debug.crop_list", "v": 1, "ts": TS, "request_id": "r1"},
    {"type": "debug.crops", "v": 1, "ts": TS, "request_id": "r1", "crops": [
        {"track_uuid": "tr_ab12_7", "camera_id": "cam01", "at": 1794398400.5,
         "person_id": "ANON-k3", "identity_source": "reid"}]},
    {"type": "debug.crop_request", "v": 1, "ts": TS, "request_id": "r2", "track_uuid": "tr_ab12_7"},
    {"type": "debug.crop", "v": 1, "ts": TS, "request_id": "r2", "track_uuid": "tr_ab12_7", "found": False},
    {"type": "debug.crop", "v": 1, "ts": TS, "request_id": "r2", "track_uuid": "tr_ab12_7", "found": True,
     "camera_id": "cam01", "at": 1794398400.5, "width": 60, "height": 200, "jpeg_b64": "AAAA"},
]
TIDAK_SAH = [
    {"type": "debug.subscribe", "v": 1, "ts": TS},                                   # tanpa enabled
    {"type": "debug.log", "v": 1, "ts": TS, "level": "INFO", "logger": "x", "message": "y"},   # INFO tidak diteruskan
    {"type": "debug.crop_request", "v": 1, "ts": TS, "request_id": "r", "track_uuid": "../../etc"},
    {"type": "debug.crop", "v": 1, "ts": TS, "request_id": "r", "track_uuid": "tr_a", "found": True},  # tanpa gambar
    {"type": "debug.rahasia", "v": 1, "ts": TS},
]


@pytest.mark.parametrize("message", SAH, ids=lambda m: m["type"])
def test_pesan_debug_sah(message):
    assert list(VALIDATOR.iter_errors(message)) == []


@pytest.mark.parametrize("message", TIDAK_SAH, ids=lambda m: m["type"])
def test_pesan_debug_tidak_sah_ditolak(message):
    assert list(VALIDATOR.iter_errors(message))


def test_debug_tidak_pernah_durabel():
    """Tidak ada pesan debug di kanal `events`: tidak masuk outbox, tidak di-ACK, tidak diputar ulang."""
    channels = {name: definition["x-channel"] for name, definition in DEBUG["$defs"].items()
                if "x-channel" in definition}
    assert len(channels) == 6 and set(channels.values()) <= {"control", "view"}


def test_kontrak_produksi_dan_fixture_bersih_dari_debug():
    assert '"debug.' not in json.dumps(MAIN), "pesan debug bocor ke kontrak produksi"
    for fixture in sorted((ROOT / "fixtures").iterdir()):
        assert "debug." not in fixture.read_text(encoding="utf-8"), f"pesan debug di fixture {fixture.name}"


def test_kontrak_debug_belum_kedaluwarsa():
    assert datetime.date.today() <= KEDALUWARSA, (
        f"Kontrak debug sementara kedaluwarsa {KEDALUWARSA}. Hapus (lihat komentar KEDALUWARSA) "
        "atau angkat menjadi kontrak resmi lewat keputusan EA; jangan sekadar memundurkan tanggal."
    )
