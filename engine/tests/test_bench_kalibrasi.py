"""Bench: `--set` override and one shared detector for N cameras."""

from __future__ import annotations

import dataclasses
import json

import pytest

from engine import factory
from engine.bench import compare
from engine.bench.cli import parse_overrides
from engine.bench.runner import _shared_detector, apply_overrides
from engine.config import load_config
from engine.tests.test_shared_detector import FakeInner


def _video_config():
    return dataclasses.replace(load_config(None), source_type="video_file")


def test_override_mengubah_field_dan_tervalidasi():
    config = apply_overrides(
        load_config(None),
        parse_overrides(["detector.nms_iou_threshold=0.7", "tracker.track_buffer_seconds=2",
                         "detector.cuda_graph=false", "target_fps=10"]),
    )
    assert config.detector.nms_iou_threshold == 0.7
    assert config.tracker.track_buffer_seconds == 2
    assert config.detector.cuda_graph is False
    assert config.target_fps == 10
    # Nilai yang ditolak loader YAML ditolak juga di sini.
    with pytest.raises(ValueError):
        apply_overrides(load_config(None), {"detector.cuda_graph": "kadang"})
    with pytest.raises(ValueError):
        apply_overrides(load_config(None), {"detector.tidak_ada": 1})
    with pytest.raises(ValueError):
        apply_overrides(load_config(None), {"bukan_bagian.x": 1})
    with pytest.raises(SystemExit):
        parse_overrides(["tanpa-sama-dengan"])


def test_banyak_kamera_satu_model_satu_kamera_tidak_dibagi(monkeypatch):
    built = []
    monkeypatch.setattr(factory, "build_detector", lambda config: built.append(FakeInner()) or built[-1])

    assert _shared_detector(_video_config(), cameras=1) is None
    no_share = _video_config()
    no_share = dataclasses.replace(
        no_share, detector=dataclasses.replace(no_share.detector, share_across_cameras=False))
    assert _shared_detector(no_share, cameras=5) is None
    assert built == []

    shared = _shared_detector(_video_config(), cameras=5)
    try:
        handles = {shared.handle(f"cam{i}") for i in range(5)}
        assert len(built) == 1 and len(handles) == 5
    finally:
        shared.stop()


def test_compare_membaca_laporan(tmp_path):
    report = {
        "run": {"label": "k1", "cameras": 1},
        "config": {"effective": {"detector": {"nms_iou_threshold": 0.7}, "tracker": {}}},
        "metrics": {
            "throughput": {"per_camera": [{"fps": 30.0}]},
            "latency": {"stages": {"detector_infer": {"p50_ms": 17.0}}},
            "track_lifetime": {"raw_seconds": {"count": 300, "p50": 2.0},
                               "stitched_seconds": {"N=2s": {"count": 200}, "N=30s": {"count": 100}}},
        },
    }
    (tmp_path / "baseline.json").write_text(json.dumps(report))
    assert compare.main([str(tmp_path)]) == 0
    assert compare.row(report)["raw/2s"] == 1.5


def test_caveat_reid_dan_rekognisi_tidak_dijalankan():
    from engine.bench.runner import _not_run_caveats

    base = load_config(None)
    off = dataclasses.replace(base, recognition=dataclasses.replace(base.recognition, enabled=False),
                              reid=dataclasses.replace(base.reid, enabled=False))
    assert _not_run_caveats(off) == []
    on = load_config("engine/config/demo-4060.yaml")  # rekognisi + ReID menyala
    assert "recognition and reid are enabled" in _not_run_caveats(on)[0]
