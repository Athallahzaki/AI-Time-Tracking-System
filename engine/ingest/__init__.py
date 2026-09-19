"""
Frame sources. OpenCV for now; PyAV with real PTS arrives in step 2.

`cv_stream` is ported so the old behaviour is reproducible, but nothing in B0
or B1 should build on it: cv2.VideoCapture.read() throws the PTS away, and
every timestamp in ARCHITECTURE.md §6.6 depends on having it.
"""

from __future__ import annotations

from typing import Any

_LAZY = {
    "BaseFrameSource": "base",
    "OpenCVStreamSource": "cv_stream",
    "VideoFileSource": "video_file",
    "MockFrameSource": "mock_source",
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
