"""
What is visible: detection, tracking, cropping. No notion of identity.

Imports are lazy on purpose. `dfine_detector` and `bytetrack_tracker` pull in LibreYOLO only when selected.
Importing them eagerly would make the mock path — the one that lets the
pipeline and the benchmark run in CI without a GPU or model weights —
impossible.
"""

from __future__ import annotations

from typing import Any

_LAZY = {
    "DFINEDetector": "dfine_detector",
    "MockDetector": "mock_detector",
    "ByteTrackTracker": "bytetrack_tracker",
    "IoUTracker": "iou_tracker",
    "MockTracker": "mock_tracker",
    "BoundingBoxPersonCropper": "person_cropper",
}

__all__ = list(_LAZY)


def __getattr__(name: str) -> Any:
    module_name = _LAZY.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    module = importlib.import_module(f".{module_name}", __name__)
    return getattr(module, name)


def __dir__() -> list[str]:
    return sorted(__all__)
