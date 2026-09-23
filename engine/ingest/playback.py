"""Wall-clock pacing for recorded files used by the interactive runtime."""

from __future__ import annotations

import time
from typing import Any, Optional, Tuple


class PlaybackSource:
    """Prevent a file source from running ahead of its media PTS.

    Unlike the benchmark realtime wrapper this class never drops a frame. If
    inference is slower than playback, the browser can wait for AI; if it is
    faster, this wrapper sleeps until the frame's presentation deadline.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self._started_at: Optional[float] = None
        self._first_pts: Optional[float] = None
        self._epoch: Optional[int] = None

    def start(self) -> None:
        self._inner.start()
        self._started_at = time.perf_counter()
        self._first_pts = None
        self._epoch = None

    def stop(self) -> None:
        self._inner.stop()

    def read(self) -> Any:
        frame = self._inner.read()
        if frame is None:
            return None

        metadata = getattr(frame, "metadata", None)
        pts = getattr(metadata, "pts", None) if metadata is not None else None
        epoch = getattr(metadata, "stream_epoch", 0) if metadata is not None else 0
        if pts is None:
            return frame

        if self._epoch != epoch or self._first_pts is None or self._started_at is None:
            self._epoch = epoch
            self._first_pts = float(pts)
            self._started_at = time.perf_counter()

        deadline = self._started_at + max(0.0, float(pts) - self._first_pts)
        remaining = deadline - time.perf_counter()
        if remaining > 0:
            time.sleep(remaining)
        return frame

    @property
    def is_running(self) -> bool:
        return bool(getattr(self._inner, "is_running", False))

    @property
    def fps(self) -> float:
        return float(getattr(self._inner, "fps", 0.0) or 0.0)

    @property
    def resolution(self) -> Tuple[int, int]:
        return getattr(self._inner, "resolution", (0, 0))

    @property
    def source_id(self) -> str:
        return getattr(self._inner, "source_id", "unknown")

    @property
    def total_frames(self) -> int:
        return int(getattr(self._inner, "total_frames", 0) or 0)

