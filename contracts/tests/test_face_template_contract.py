"""Kontrak template wajah (contracts/schema/face_template.schema.json, paket ea-r31).

Dijaga: pesan sah lolos, pesan cacat ditolak, kontrak ini terpisah dari kontrak
produksi dan fixture, dan tidak ada satu pun pesannya yang durabel.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schema" / "face_template.schema.json").read_text(encoding="utf-8"))
MAIN = json.loads((ROOT / "schema" / "engine_protocol.schema.json").read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA)

TS = "2026-11-12T08:00:00.000Z"
ITEM = {
    "candidate_id": "ft_ab12cd34", "person_id": "EMP-001", "camera_id": "cam01", "captured_at": TS,
    "track_uuid": "tr_ab12_7", "jpeg_b64": "AAAA", "embedding_b64": "AAAA",
    "anchor_similarity": 0.52, "runner_up_id": "EMP-002", "runner_up_similarity": 0.21,
    "margin": 0.31, "face_px": 64.0, "det_score": 0.81, "yaw": 0.12,
}
SAH = [
    {"type": "template.pull", "v": 1, "ts": TS, "request_id": "r1", "max_items": 20},
    {"type": "template.candidates", "v": 1, "ts": TS, "channel": "control", "request_id": "r1",
     "embedding_version": "auraface-v1", "items": [ITEM]},
    {"type": "template.candidates", "v": 1, "ts": TS, "request_id": "r1",
     "embedding_version": "auraface-v1", "items": []},
    {"type": "template.apply", "v": 1, "ts": TS, "request_id": "r2", "items": [
        {"candidate_id": "ft_ab12cd34", "person_id": "EMP-001", "jpeg_b64": "AAAA",
         "embedding_b64": "AAAA", "embedding_version": "auraface-v1", "camera_id": "cam01", "captured_at": TS}]},
    {"type": "template.applied", "v": 1, "ts": TS, "request_id": "r2", "items": [
        {"candidate_id": "ft_ab12cd34", "accepted": True, "reference_id": 41},
        {"candidate_id": "ft_ff", "accepted": False, "reason": "margin_tipis"}]},
    {"type": "template.remove", "v": 1, "ts": TS, "request_id": "r3", "reference_ids": [41]},
    {"type": "template.removed", "v": 1, "ts": TS, "request_id": "r3", "removed": 1},
]
TIDAK_SAH = [
    {"type": "template.pull", "v": 1, "ts": TS},                                          # tanpa request_id
    {"type": "template.pull", "v": 1, "ts": TS, "request_id": "r", "max_items": 500},     # terlalu banyak
    {"type": "template.candidates", "v": 1, "ts": TS, "request_id": "r", "embedding_version": "x",
     "items": [{k: v for k, v in ITEM.items() if k != "jpeg_b64"}]},                       # tanpa gambar
    {"type": "template.apply", "v": 1, "ts": TS, "request_id": "r", "items": []},          # kosong
    {"type": "template.apply", "v": 1, "ts": TS, "request_id": "r", "items": [
        {**{k: ITEM[k] for k in ("person_id", "jpeg_b64", "embedding_b64")},
         "candidate_id": "../x", "embedding_version": "v"}]},                               # id berbahaya
    {"type": "template.remove", "v": 1, "ts": TS, "request_id": "r", "reference_ids": [0]},
    {"type": "template.hapus_semua", "v": 1, "ts": TS},
]


@pytest.mark.parametrize("message", SAH, ids=lambda m: m["type"])
def test_pesan_template_sah(message):
    assert list(VALIDATOR.iter_errors(message)) == []


@pytest.mark.parametrize("message", TIDAK_SAH, ids=lambda m: m["type"])
def test_pesan_template_tidak_sah_ditolak(message):
    assert list(VALIDATOR.iter_errors(message))


def test_template_tidak_pernah_durabel():
    channels = {name: definition["x-channel"] for name, definition in SCHEMA["$defs"].items()
                if "x-channel" in definition}
    assert len(channels) == 6 and set(channels.values()) == {"control"}


def test_kontrak_produksi_dan_fixture_bersih_dari_template():
    assert '"template.' not in json.dumps(MAIN), "pesan template bocor ke kontrak produksi"
    for fixture in sorted((ROOT / "fixtures").iterdir()):
        assert '"template.' not in fixture.read_text(encoding="utf-8"), f"pesan template di {fixture.name}"
