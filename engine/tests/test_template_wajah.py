"""Template wajah dari CCTV (identity/templates.py, paket ea-r31).

Yang dijaga: hanya bukti yang cocok dengan JANGKAR orangnya dan jauh dari orang lain
yang jadi kandidat; engine tidak pernah memasang sendiri; pemasangan diperiksa ulang;
jangkar enrollment tidak pernah terhapus; pesan yang dikirim sah terhadap skemanya.
"""
from __future__ import annotations

import base64
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from jsonschema import Draft202012Validator

from engine.config import load_config
from engine.config.schema import FaceTemplateConfig
from engine.identity import MatrixMatcher
from engine.identity.face_onnx import FaceDetection, OnnxFaceRecognizer
from engine.identity.ports import Evidence
from engine.identity.templates import FaceTemplateCollector, decode_embedding, encode_embedding
from engine.runtime.service import EngineRuntime
from engine.store.references import SqliteReferenceStore

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = Draft202012Validator(json.loads(
    (ROOT / "contracts" / "schema" / "face_template.schema.json").read_text(encoding="utf-8")))
DIM = 8
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 32
TS = "2026-11-12T08:00:00.000Z"


def _unit(*values):
    vector = np.zeros(DIM, np.float32)
    vector[: len(values)] = values
    return vector / np.linalg.norm(vector)


# Budi di sumbu 0, Andi di sumbu 1. Wajah CCTV Budi: miring ke sumbu 2.
BUDI = _unit(1.0)
ANDI = _unit(0, 1.0)
BUDI_CCTV = _unit(0.8, 0.0, 0.6)          # 0.8 ke jangkar Budi, 0 ke Andi
DI_TENGAH = _unit(0.7, 0.68)               # mirip keduanya: margin tipis


@pytest.fixture
def setup(tmp_path):
    store = SqliteReferenceStore(tmp_path / "refs.db", embedding_version="v1", dimension=DIM)
    store.add_reference("budi", BUDI, JPEG, 0.9)
    store.add_reference("andi", ANDI, JPEG, 0.9)
    matcher = MatrixMatcher(store, threshold=0.37, margin=0.06)
    now = [1000.0]
    collector = FaceTemplateCollector(FaceTemplateConfig(enabled=True), store, matcher,
                                      clock=lambda: now[0], encode_jpeg=lambda image: JPEG)
    return SimpleNamespace(store=store, matcher=matcher, collector=collector, now=now)


def _bukti(vector, face_px=64.0, det_score=0.8, yaw=0.1, version="v1"):
    return Evidence(embedding=vector, pts=1.0, embedding_version=version,
                    face_crop=np.zeros((10, 10, 3), np.uint8), face_px=face_px, det_score=det_score, yaw=yaw)


def test_bukti_bagus_jadi_kandidat_dan_pesannya_sah(setup):
    assert setup.collector.offer("budi", "cam01", "tr_ab_1", _bukti(BUDI_CCTV)) is None
    items = setup.collector.pull(20)
    assert len(items) == 1 and items[0]["person_id"] == "budi"
    assert items[0]["anchor_similarity"] == pytest.approx(0.8, abs=1e-3)
    assert items[0]["runner_up_id"] == "andi"
    message = {"type": "template.candidates", "v": 1, "ts": TS, "channel": "control",
               "request_id": "r1", "embedding_version": "v1", "items": items}
    assert list(SCHEMA.iter_errors(message)) == []
    assert setup.collector.pull(20) == [], "kandidat yang sudah ditarik hilang dari buffer"
    assert setup.store.vectors_of("budi").shape[0] == 1, "tangkap TIDAK PERNAH menulis referensi"


@pytest.mark.parametrize("bukti, alasan", [
    (dict(vector=BUDI_CCTV, face_px=30.0), "kecil"),
    (dict(vector=BUDI_CCTV, det_score=0.3), "skor_detektor"),
    (dict(vector=BUDI_CCTV, yaw=0.9), "menyamping"),
    (dict(vector=BUDI_CCTV, version="v2"), "versi_berbeda"),
    (dict(vector=_unit(0, 0, 1.0)), "jangkar_rendah"),
    (dict(vector=DI_TENGAH), "margin_tipis"),
    (dict(vector=BUDI), "duplikat"),
])
def test_bukti_ditolak_dengan_alasan(setup, bukti, alasan):
    vector = bukti.pop("vector")
    assert setup.collector.offer("budi", "cam01", "tr_ab_1", _bukti(vector, **bukti)) == alasan
    assert setup.collector.pull(20) == []
    assert setup.collector.counters[f"tolak_{alasan}"] == 1


def test_orang_tanpa_jangkar_tidak_bisa_punya_template(setup):
    assert setup.collector.offer("cici", "cam01", "tr_ab_1", _bukti(BUDI_CCTV)) == "tanpa_jangkar"


def test_jeda_per_orang(setup):
    assert setup.collector.offer("budi", "cam01", "tr_ab_1", _bukti(BUDI_CCTV)) is None
    setup.now[0] += 30
    assert setup.collector.offer("budi", "cam02", "tr_ab_2", _bukti(_unit(0.8, 0, 0, 0.6))) == "jeda"
    setup.now[0] += 31
    assert setup.collector.offer("budi", "cam02", "tr_ab_2", _bukti(_unit(0.8, 0, 0, 0.6))) is None


def test_buffer_terbatas_membuang_yang_tertua(tmp_path, setup):
    collector = FaceTemplateCollector(FaceTemplateConfig(enabled=True, buffer_size=2,
                                                         per_person_cooldown_seconds=0),
                                      setup.store, setup.matcher, encode_jpeg=lambda image: JPEG)
    for index in range(3):
        assert collector.offer("budi", f"cam0{index}", "tr_ab_1", _bukti(_unit(0.8, 0, 0, 0, 0.6, index * 0.1))) is None
    assert [item["camera_id"] for item in collector.pull(20)] == ["cam01", "cam02"]
    assert collector.counters["dibuang_buffer_penuh"] == 1


def _item(vector, candidate_id="ft_a1", person_id="budi", version="v1"):
    return {"candidate_id": candidate_id, "person_id": person_id, "embedding_version": version,
            "embedding_b64": encode_embedding(vector), "jpeg_b64": base64.b64encode(JPEG).decode(),
            "camera_id": "cam01", "captured_at": TS}


def test_pasang_menambah_template_learned_dan_menaikkan_skor(setup):
    before = setup.matcher.match(BUDI_CCTV).similarity
    results = setup.collector.apply([_item(BUDI_CCTV)])
    assert results[0]["accepted"] is True and results[0]["reference_id"] > 0
    assert setup.store.vectors_of("budi", source="learned").shape[0] == 1
    assert setup.store.vectors_of("budi", source="enroll").shape[0] == 1
    assert setup.matcher.match(BUDI_CCTV).similarity > before, "matcher dibangun ulang"
    message = {"type": "template.applied", "v": 1, "ts": TS, "request_id": "r", "items": results}
    assert list(SCHEMA.iter_errors(message)) == []


def test_pasang_diperiksa_ulang(setup):
    results = setup.collector.apply([
        _item(BUDI_CCTV, "ft_a1"),
        _item(BUDI_CCTV, "ft_a2"),                        # kembar dalam satu batch
        _item(BUDI_CCTV, "ft_a3", version="v0"),
        _item(DI_TENGAH, "ft_a4"),
        {**_item(BUDI_CCTV, "ft_a5"), "embedding_b64": "AAAA"},
        {**_item(_unit(0.8, 0, 0, 0.6), "ft_a6"), "jpeg_b64": base64.b64encode(b"bukan jpeg").decode()},
        _item(BUDI_CCTV, "ft_a7", person_id="cici"),
    ])
    assert [(r["candidate_id"], r["accepted"], r.get("reason")) for r in results] == [
        ("ft_a1", True, None), ("ft_a2", False, "duplikat"), ("ft_a3", False, "versi_berbeda"),
        ("ft_a4", False, "margin_tipis"), ("ft_a5", False, "embedding_rusak"),
        ("ft_a6", False, "gambar_rusak"), ("ft_a7", False, "tanpa_jangkar"),
    ]


def test_cabut_hanya_menghapus_learned(setup):
    reference_id = setup.collector.apply([_item(BUDI_CCTV)])[0]["reference_id"]
    anchor_ids = [record.reference_id for record in setup.store.records("budi")
                  if record.reference_id != reference_id]
    assert setup.collector.remove(anchor_ids + [reference_id, 99999]) == 1
    assert setup.store.vectors_of("budi").shape[0] == 1, "jangkar enrollment tetap utuh"
    assert setup.store.vectors_of("budi", source="learned").shape[0] == 0


def test_embedding_bolak_balik():
    assert np.allclose(decode_embedding(encode_embedding(BUDI_CCTV), DIM), BUDI_CCTV)
    assert decode_embedding("!!", DIM) is None
    assert decode_embedding(base64.b64encode(b"\0" * DIM * 4).decode(), DIM) is None


def test_store_lama_mendapat_kolom_source(tmp_path):
    path = tmp_path / "lama.db"
    db = sqlite3.connect(path)
    db.executescript(
        "CREATE TABLE persons (person_id TEXT PRIMARY KEY, enrollment_version INTEGER NOT NULL, updated_at TEXT NOT NULL);"
        "CREATE TABLE refs (reference_id INTEGER PRIMARY KEY AUTOINCREMENT, person_id TEXT NOT NULL, "
        "embedding_version TEXT NOT NULL, enrollment_version INTEGER NOT NULL, vector BLOB NOT NULL, "
        "image BLOB NOT NULL, quality REAL NOT NULL, camera_id TEXT, captured_at TEXT, created_at TEXT NOT NULL);"
        "INSERT INTO persons VALUES ('budi', 1, 'x');")
    db.execute("INSERT INTO refs (person_id, embedding_version, enrollment_version, vector, image, quality, created_at) "
               "VALUES ('budi', 'v1', 1, ?, ?, 0.9, 'x')", (BUDI.tobytes(), JPEG))
    db.commit()
    db.close()
    store = SqliteReferenceStore(path, embedding_version="v1", dimension=DIM)
    assert store.vectors_of("budi", source="enroll").shape[0] == 1
    assert store.delete_learned([1]) == 0


def test_recognizer_menangkap_crop_hanya_bila_diminta():
    landmarks = np.array([[30, 40], [70, 40], [50, 60], [35, 80], [65, 80]], np.float32) * 0.64
    face = FaceDetection(bbox=(10.0, 10.0, 74.0, 74.0), score=0.9, landmarks=landmarks + 10)

    class Detector:
        def detect(self, crop):
            return [face]

    class Embedder:
        input_size = 112

        def embed(self, aligned):
            return BUDI

    recognizer = OnnxFaceRecognizer(Detector(), Embedder(), "v1", min_face_px=40)
    track = SimpleNamespace(bbox=SimpleNamespace(x1=100, y1=50, x2=300, y2=450))
    frame = SimpleNamespace(image=np.zeros((600, 600, 3), np.uint8), metadata=SimpleNamespace(pts=1.0))
    assert recognizer(track, frame).face_crop is None
    recognizer.capture_face_crops = True
    evidence = recognizer(track, frame)
    assert evidence.face_crop.shape[:2] == (128, 128)          # 64 px x 2
    assert evidence.face_px == 64.0 and evidence.det_score == pytest.approx(0.9)
    assert evidence.yaw == pytest.approx(0.0, abs=1e-6)


def test_config_default_mati_dan_dibaca(tmp_path):
    assert load_config().face_templates.enabled is False
    path = tmp_path / "c.yaml"
    path.write_text("face_templates:\n  enabled: true\n  min_margin: 0.2\n", encoding="utf-8")
    config = load_config(str(path)).face_templates
    assert config.enabled is True and config.min_margin == 0.2
    with pytest.raises(ValueError):
        FaceTemplateConfig(min_det_score=2.0)


def test_engine_tanpa_penangkap_menolak_dengan_alasan():
    runtime = SimpleNamespace(_templates=None)
    reply = EngineRuntime._on_template(runtime, {"type": "template.pull", "request_id": "r1"})
    assert reply["type"] == "ack" and reply["accepted"] is False and reply["in_reply_to"] == "template.pull"


def test_engine_menjawab_pull_dan_apply(setup):
    import threading

    runtime = SimpleNamespace(_templates=setup.collector, _store=setup.store, _emit_lock=threading.Lock())
    setup.collector.offer("budi", "cam01", "tr_ab_1", _bukti(BUDI_CCTV))
    reply = EngineRuntime._on_template(runtime, {"type": "template.pull", "request_id": "r1", "max_items": 5})
    reply["channel"] = "control"
    assert reply["type"] == "template.candidates" and list(SCHEMA.iter_errors(reply)) == []
    item = reply["items"][0]
    apply_reply = EngineRuntime._on_template(runtime, {"type": "template.apply", "request_id": "r2", "items": [
        {key: item[key] for key in ("candidate_id", "person_id", "jpeg_b64", "embedding_b64", "camera_id",
                                    "captured_at")} | {"embedding_version": "v1"}]})
    assert apply_reply["items"][0]["accepted"] is True
    remove_reply = EngineRuntime._on_template(runtime, {"type": "template.remove", "request_id": "r3",
                                                        "reference_ids": [apply_reply["items"][0]["reference_id"]]})
    assert remove_reply["removed"] == 1 and list(SCHEMA.iter_errors(remove_reply)) == []
