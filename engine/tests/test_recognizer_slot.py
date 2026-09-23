"""Slot recognizer: mati secara default, bisa dinyalakan lewat config,
dan gagal keras kalau diminta tapi tidak bisa dimuat."""
from __future__ import annotations

import base64
import time

import numpy as np
import pytest

from contracts.validator import SchemaValidator
from engine.config import load_config
from engine.config.schema import RecognitionConfig
from engine.identity.face_onnx import (
    FaceAnalysis,
    RecognizerUnavailable,
    align_face,
    build_recognizer,
)


def test_default_config_has_no_recognizer():
    config = load_config("engine/config/default_config.yaml")
    assert config.recognition.recognizer == "none"
    assert build_recognizer(config.recognition) is None


def test_recognizer_without_scheduler_is_refused():
    with pytest.raises(ValueError, match="enabled is false"):
        RecognitionConfig(enabled=False, recognizer="onnx_face",
                          face_detector_model="a.onnx", face_embedder_model="b.onnx")


def test_recognizer_requested_but_missing_fails_loudly(tmp_path):
    config = RecognitionConfig(
        enabled=True, recognizer="onnx_face",
        face_detector_model=str(tmp_path / "missing_det.onnx"),
        face_embedder_model=str(tmp_path / "missing_emb.onnx"),
    )
    with pytest.raises(RecognizerUnavailable):
        build_recognizer(config)


def test_alignment_produces_arcface_crop():
    image = np.full((400, 400, 3), 128, dtype=np.uint8)
    landmarks = np.array([[160, 180], [240, 180], [200, 230], [170, 270], [230, 270]],
                         dtype=np.float32)
    aligned = align_face(image, landmarks, 112)
    assert aligned.shape == (112, 112, 3)


class _StubRecognizer:
    """Stands in for OnnxFaceRecognizer: deterministic, distinct embeddings."""

    def __init__(self):
        self._rng = np.random.default_rng(7)

    def __call__(self, track, frame):
        return None

    def analyze_image(self, bgr):
        vector = self._rng.normal(size=512).astype(np.float32)
        vector /= np.linalg.norm(vector)
        return FaceAnalysis(
            face_count=1, embedding=vector, face_width=180, face_height=200,
            sharpness=400.0, brightness=120.0, contrast=50.0, detector_confidence=0.95,
            landmarks=[[60, 80], [120, 80], [90, 110], [65, 140], [115, 140]],
        )


def _jpeg() -> str:
    import cv2
    ok, buf = cv2.imencode(".jpg", np.full((240, 240, 3), 120, dtype=np.uint8))
    assert ok
    return base64.b64encode(buf.tobytes()).decode()


def test_enrollment_with_a_recognizer_commits_references(tmp_path):
    from engine.identity import MatrixMatcher
    from engine.runtime.service import EngineRuntime, RuntimeOptions
    from engine.store.references import SqliteReferenceStore

    store = SqliteReferenceStore(tmp_path / "refs.sqlite3", "auraface-v1")
    matcher = MatrixMatcher(store)
    runtime = EngineRuntime(
        config=load_config("engine/config/default_config.yaml"),
        options=RuntimeOptions(tcp=None),
        recognize=_StubRecognizer(), reference_store=store, matcher=matcher,
    )
    try:
        reply = runtime._on_enroll({
            "type": "enroll", "v": 1, "request_id": "e-9", "person_id": "4471",
            "enrollment_version": 1,
            "images": [{"id": f"img{i}", "jpeg_b64": _jpeg()} for i in range(3)],
        })
        assert reply["type"] == "enroll_result"
        assert reply["request_id"] == "e-9"
        assert reply["accepted"] is True, reply
        assert matcher.person_count == 1
        issues = SchemaValidator().validate_message({**reply, "channel": "control"})
        assert not issues, issues
    finally:
        runtime.close()
        store.close()


def test_failed_camera_is_reopened(monkeypatch, tmp_path):
    from engine.runtime import camera as camera_module
    from engine.runtime.camera import CameraSpec, CameraSupervisor

    monkeypatch.setattr(camera_module, "RETRY_INITIAL_SECONDS", 0.05)
    emitted = []
    config = load_config("engine/config/default_config.yaml")
    import dataclasses
    config = dataclasses.replace(config, source_uri=str(tmp_path / "missing.mp4"),
                                 source_type="video_file")
    supervisor = CameraSupervisor(
        spec=CameraSpec("r9", str(tmp_path / "missing.mp4")), config=config,
        emit_event=emitted.append, emit_view=lambda m: True,
    )
    supervisor.start()
    try:
        deadline = time.time() + 5
        while time.time() < deadline and supervisor.stats.attempts < 2:
            time.sleep(0.05)
        assert supervisor.stats.attempts >= 2, "camera was not retried"
        assert supervisor.alive
        assert sum(1 for e in emitted if e["type"] == "camera.failed") >= 2
    finally:
        supervisor.stop()
    assert not supervisor.alive
