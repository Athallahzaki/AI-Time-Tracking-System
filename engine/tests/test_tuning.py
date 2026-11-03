"""Pengaturan realtime `set_tuning` (overhaul 3 Nov): tanpa restart, deklaratif, semua-atau-tidak."""
from __future__ import annotations

import time

import pytest

from contracts.validator import SchemaValidator
from engine.config import load_config
from engine.runtime.tuning import TUNABLE, TuningError, apply_detector_tuning, effective, tuned_config

BASE = "engine/config/default_config.yaml"


def test_override_kosong_sama_dengan_file():
    base = load_config(BASE)
    assert tuned_config(base, {}) == base
    eff = effective(base)
    assert set(eff) == set(TUNABLE) and eff["analysis_trigger"]["enabled"] is False


def test_override_diterapkan_dan_divalidasi_dataclass_yang_sama():
    base = load_config(BASE)
    config = tuned_config(base, {
        "recognition": {"match_threshold": 0.42, "cross_camera_claims": True,
                        "overlapping_cameras": [["cam_lobby", "cam_luar"]]},
        "reid": {"match_threshold": 0.75, "travel_time_seconds": {"lobby": {"biliar": 20}}, "reevaluate": True},
        "analysis_trigger": {"enabled": True, "sustain_frames": 4},
        "detector": {"confidence_threshold": 0.55, "nms_iou_threshold": 0.7},
        "core": {"idle_fps": 1.0},
    })
    assert config.recognition.overlapping_cameras == (("cam_lobby", "cam_luar"),)
    assert config.reid.merge_config().reevaluate is True
    assert config.analysis_trigger.sustain_frames == 4 and config.idle_fps == 1.0
    assert config.detector.model_path == base.detector.model_path, "yang tidak disebut tetap dari file"


@pytest.mark.parametrize("bad", [
    {"tracker": {"track_threshold": 0.3}},                     # butuh restart
    {"detector": {"model_path": "x.pt"}},
    {"analysis_trigger": {"sustain_frames": 0}},               # __post_init__ menolak
    {"analysis_trigger": {"swap_iou": 0.01}},
    {"recognition": {"match_threshold": 2.0}},
    {"detector": {"confidence_threshold": "tinggi"}},
    {"recognition": {"overlapping_cameras": [["cam_a", "cam_a"]]}},
    {"core": {"idle_fps": -1}},
    [],
])
def test_nilai_tidak_sah_ditolak_utuh(bad):
    with pytest.raises(TuningError):
        tuned_config(load_config(BASE), bad)


def test_detector_ambang_turun_ikut_menurunkan_permintaan_ke_model_tapi_tidak_naik_di_atas_lantai():
    class Fake:
        _conf, _raw_conf, _nms_iou = 0.5, 0.1, None

    det = Fake()
    apply_detector_tuning(det, type("C", (), {"confidence_threshold": 0.3, "nms_iou_threshold": 0.7})())
    assert (det._conf, det._raw_conf, det._nms_iou) == (0.3, 0.1, 0.7)
    apply_detector_tuning(det, type("C", (), {"confidence_threshold": 0.05, "nms_iou_threshold": None})())
    assert det._raw_conf == 0.05
    apply_detector_tuning(det, type("C", (), {"confidence_threshold": 0.6, "nms_iou_threshold": None})())
    assert det._raw_conf == 0.1, "kembali ke lantai start, bukan naik ke 0,6 (ByteTrack butuh kotak rendah)"


def test_runtime_menerapkan_set_tuning_tanpa_restart_dan_ack_lolos_skema():
    from engine.identity import InMemoryReferenceStore, MatrixMatcher
    from engine.runtime.service import EngineRuntime, RuntimeOptions

    runtime = EngineRuntime(config=load_config(BASE), options=RuntimeOptions(tcp=None))
    runtime._matcher = MatrixMatcher(InMemoryReferenceStore({}))
    validator = SchemaValidator()
    try:
        message = {"type": "set_tuning", "v": 1, "ts": "2026-11-03T01:00:00.000Z", "tuning": {
            "recognition": {"match_threshold": 0.45, "match_margin": 0.08, "cross_camera_claims": True,
                            "overlapping_cameras": [["cam01", "cam02"]]},
            "analysis_trigger": {"enabled": True}}}
        assert validator.validate_message(message, expected_channel="control") == []
        ack = runtime._on_set_tuning(message)
        assert ack["accepted"] is True, ack
        assert validator.validate_message(ack, expected_channel="control") == []
        assert (runtime._matcher._threshold, runtime._matcher._margin) == (0.45, 0.08)
        assert runtime._cross_camera.enabled and runtime._cross_camera.overlaps("cam02", "cam01")
        assert ack["effective_tuning"]["analysis_trigger"]["enabled"] is True

        rejected = runtime._on_set_tuning({"type": "set_tuning", "tuning": {"recognition": {"match_margin": -1}}})
        assert rejected["accepted"] is False and "match_margin" in rejected["reason"]
        assert runtime._matcher._margin == 0.08, "ditolak = pengaturan sebelumnya tetap"

        reset = runtime._on_set_tuning({"type": "set_tuning", "tuning": {}})
        assert reset["accepted"] and not runtime._cross_camera.enabled, "{} = kembali ke file"
        assert runtime.config.analysis_trigger.enabled is False
    finally:
        runtime.close()


def test_kamera_menerima_gerbang_dan_idle_baru():
    from types import SimpleNamespace

    from engine.pipeline.change_gate import ChangeGate
    from engine.runtime.camera import CameraSupervisor

    config = tuned_config(load_config(BASE), {"analysis_trigger": {"enabled": True, "sustain_frames": 5},
                                              "core": {"idle_fps": 2.0}})
    camera = CameraSupervisor.__new__(CameraSupervisor)
    camera._change_gate = ChangeGate(load_config(BASE).analysis_trigger)
    camera._detector = None
    camera._engine = SimpleNamespace(detection_gate=None)
    camera._idle_gate = None
    camera.apply_tuning(config)
    assert camera._change_gate.params.enabled and camera._change_gate.params.sustain_frames == 5
    assert camera._engine.detection_gate is not None and camera._config is config
    camera.apply_tuning(load_config(BASE))
    assert camera._engine.detection_gate is None and not camera._change_gate.params.enabled
