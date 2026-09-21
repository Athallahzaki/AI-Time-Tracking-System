"""Configuration and dependency boundary checks for the D-FINE adapter."""

from __future__ import annotations

import ast
from pathlib import Path

from engine.config import DetectorConfig, EngineConfig


def test_dfine_is_the_default_real_detector():
    config = EngineConfig()
    assert config.detector == DetectorConfig()
    assert config.detector.model_path == "ustc-community/dfine-nano-coco"
    assert config.tracker.backend == "iou"


def test_dfine_adapter_does_not_import_yolo_or_ultralytics():
    path = Path(__file__).resolve().parents[1] / "perception" / "dfine_detector.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".", 1)[0])
    assert "ultralytics" not in imports
    assert "libreyolo" not in imports


def test_only_dfine_detector_is_exported():
    from engine import perception

    assert "DFINEDetector" in perception.__all__
    assert "YOLODetector" not in perception.__all__
