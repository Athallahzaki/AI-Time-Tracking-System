"""
Frame sources.

Two backends live here for exactly one step. `pyav_source` has the real
timeline (§5.5, §6.6); `video_file` and `cv_stream` are the OpenCV originals,
kept only so B4 can measure the two against each other on the same recording
instead of asserting that swapping them was free. Once that delta is in a
committed report, the OpenCV pair leaves.

Everything about time that does not need a decoder is in `timeline.py`, which
both backends share.
"""

from __future__ import annotations

from typing import Any

_LAZY = {
    "BaseFrameSource": "base",
    "OpenCVStreamSource": "cv_stream",
    "VideoFileSource": "video_file",
    "MockFrameSource": "mock_source",
    "PyAVSource": "pyav_source",
    "PlaybackSource": "playback",
    "StreamTimeline": "timeline",
    "TimelineFidelity": "timeline",
    "Stamp": "timeline",
    "derived_pts": "timeline",
    "epochs_are_comparable": "timeline",
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
