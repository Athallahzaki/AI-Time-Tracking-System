"""engine/config/demo-1060.yaml: profil demo GTX 1060 yang dibekukan.

Tes ini menjaga keputusan dari batch_check 4 Okt supaya tidak tertimpa diam-diam
saat config lain diubah: S, FP32, cuda_graph, 8 fps, rekognisi async, live
buffer latest. Dan profilnya harus tetap bisa dimuat oleh kumulatif v13
(tanpa kunci swscale_resize).
"""

from __future__ import annotations

from pathlib import Path

import yaml

from engine.config import load_config

PATH = "engine/config/demo-1060.yaml"


def test_keputusan_demo_1060():
    config = load_config(PATH)
    detector = config.detector
    assert detector.model_path == "LibreDFINEs.pt"
    assert detector.half is False                 # Pascal
    assert detector.cuda_graph is True
    assert detector.fast_preprocess is False
    assert detector.batch_inference is False
    assert config.target_fps == 8.0
    assert config.detection_interval == 1
    assert config.ingest.live_buffer == "latest"
    recognition = config.recognition
    assert recognition.enabled and recognition.recognizer == "onnx_face"
    assert recognition.execution == "async"
    assert "CUDAExecutionProvider" in recognition.onnx_providers


def test_tanpa_kunci_yang_belum_ada_di_v13():
    raw = yaml.safe_load(Path(PATH).read_text(encoding="utf-8"))
    assert "swscale_resize" not in raw["detector"]
    assert raw["ingest"]["colour_conversion"] in ("to_ndarray", "reformatter")


def test_sisanya_sama_dengan_profil_face():
    """Hanya target_fps dan detector yang boleh berbeda dari dfine-m-face.yaml."""
    demo = yaml.safe_load(Path(PATH).read_text(encoding="utf-8"))
    face = yaml.safe_load(Path("engine/config/dfine-m-face.yaml").read_text(encoding="utf-8"))
    for section in ("ingest", "zones", "recognition", "tracker"):
        if section == "ingest":
            keep = {k: v for k, v in face[section].items() if k != "colour_conversion"}
            assert {k: demo[section][k] for k in keep} == keep
        else:
            assert demo.get(section) == face.get(section), section
    assert {k: v for k, v in demo["core"].items() if k != "target_fps"} == \
        {k: v for k, v in face["core"].items() if k != "target_fps"}
