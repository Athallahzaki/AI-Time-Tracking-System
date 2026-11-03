"""engine/config/demo-4060.yaml: profil demo RTX 4060 (keputusan uji 3 Okt)."""

from __future__ import annotations

from pathlib import Path

import yaml

from engine.config import load_config

PATH = "engine/config/demo-4060.yaml"


def test_keputusan_demo_4060():
    config = load_config(PATH)
    detector = config.detector
    assert detector.model_path == "LibreDFINEm.pt"
    assert detector.half is True and detector.cuda_graph is True
    assert detector.fast_preprocess is True and detector.pre_resize is True
    assert detector.batch_inference is False
    assert config.target_fps == 10.0 and config.detection_interval == 1
    assert config.ingest.live_buffer == "latest"
    assert config.recognition.enabled and config.recognition.execution == "async"


def test_rekognisi_dan_sisanya_sama_dengan_profil_demo_1060():
    """Beda kedua profil demo hanya di detector dan target_fps, bukan di rekognisi/ingest/tracker."""
    a = yaml.safe_load(Path(PATH).read_text(encoding="utf-8"))
    b = yaml.safe_load(Path("engine/config/demo-1060.yaml").read_text(encoding="utf-8"))
    # Boleh beda per mesin: NVDEC (1060 memakainya) dan buffer track (disetel di lapangan).
    per_machine = {"ingest": {"hwaccel"}, "tracker": {"track_buffer_seconds"}}
    for section in ("ingest", "zones", "recognition", "tracker"):
        skip = per_machine.get(section, set())
        got = {k: v for k, v in (a.get(section) or {}).items() if k not in skip}
        keep = {k: v for k, v in (b.get(section) or {}).items() if k not in skip}
        assert got == keep, section
    assert {k: v for k, v in a["core"].items() if k != "target_fps"} == \
        {k: v for k, v in b["core"].items() if k != "target_fps"}
    assert "swscale_resize" not in a["detector"]
