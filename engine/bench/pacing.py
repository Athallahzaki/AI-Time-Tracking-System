"""
The two modes, and the wall between them.

ARCHITECTURE.md §13.2:

| mode       | pacing          | drops  | answers                        |
|------------|-----------------|--------|--------------------------------|
| throughput | as fast as able | never  | what a frame costs to compute  |
| realtime   | source PTS      | may    | what actually happens in prod  |

Track lifetime, ID switch and accuracy are **only** valid from throughput — in
realtime a dropped frame breaks a track, and what gets measured is how slow the
test machine is, not how good the tracker is. Drop rate and queue depth are
**only** valid from realtime. Mixing the two produces numbers nobody can
reproduce, so the mode is a property of the run, recorded in the report, and
`metrics.py` withholds the fields the mode cannot justify rather than printing
them with a caveat somebody will skip.

The pacing lives in a source wrapper rather than in the engine because that
keeps the engine identical in both modes. A mode that changes engine code is a
mode that measures different code.

Since B4 "source PTS" means the container's own PTS whenever the source has
one, and the report's `pts_source` says which it was. The OpenCV backend still
has no PTS at all and falls back to `index / fps`; a run made on it is fine for
a constant-rate file and quietly wrong for a variable-rate one.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional, Tuple

logger = logging.getLogger("engine.bench.pacing")


class _SourceProxy:
    """Forwards everything a FrameSource is expected to expose."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def start(self) -> None:
        self._inner.start()

    def stop(self) -> None:
        self._inner.stop()

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

    def read(self) -> Any:
        return self._inner.read()


class OffsetSource(_SourceProxy):
    """
    Skips the first N frames so N simulated cameras see different moments.

    §13.2: simulating five cameras is the same file played five times with
    random time offsets. Realistic for decode and detection cost. **Not**
    realistic for identity — five copies of the same person destroy the
    per-frame dedup of §5.3 and the cross-camera fusion of §5.4 — which is why
    identity and track-quality metrics are reported for N=1 only, and why that
    restriction is printed by the bench rather than filed in a document.

    The skipped frames are decoded and discarded rather than seeked past. It
    costs a moment at startup and avoids depending on how accurately the
    container reports keyframe positions.
    """

    def __init__(self, inner: Any, offset_frames: int) -> None:
        super().__init__(inner)
        self._offset = max(0, int(offset_frames))
        self._skipped = False

    def start(self) -> None:
        self._inner.start()
        if self._skipped or self._offset == 0:
            self._skipped = True
            return
        for _ in range(self._offset):
            if self._inner.read() is None:
                break
        self._skipped = True

    @property
    def total_frames(self) -> int:
        inner_total = int(getattr(self._inner, "total_frames", 0) or 0)
        if not inner_total:
            return 0
        return max(0, inner_total - self._offset)


class RealtimeSource(_SourceProxy):
    """
    Paces reads to the source timeline and drops when the pipeline falls behind.

    Since B4 the schedule comes from each frame's own PTS when the source has a
    real one, and falls back to `index / fps` when it does not. That is not
    cosmetic: on a variable-rate recording the two schedules differ exactly
    where the recorder skipped frames, so index-based pacing would sleep for
    time that was never recorded and call the result a realtime run.

    Falling behind is the thing being measured, so the drop policy is stated
    rather than tuned: if a frame's deadline has already passed by more than one
    nominal interval, that frame is thrown away and the next is considered.
    Decoding it anyway is deliberate — decode is a real cost a production engine
    pays on every frame whether or not it analyses it, and skipping the decode
    would flatter the result.
    """

    def __init__(
        self,
        inner: Any,
        fps: float,
        recorder: Optional[Any] = None,
        max_consecutive_drops: int = 300,
    ) -> None:
        super().__init__(inner)
        if fps <= 0.0:
            raise ValueError(
                "Realtime mode needs a positive fps to pace against; got "
                f"{fps}. Guessing one would make the drop rate meaningless."
            )
        self._fps = fps
        self._interval = 1.0 / fps
        self._recorder = recorder
        self._max_consecutive_drops = max_consecutive_drops
        self._t0: Optional[float] = None
        self._first_pts: Optional[float] = None
        self._epoch: Optional[int] = None
        self._index = 0

    def start(self) -> None:
        self._inner.start()
        self._t0 = time.perf_counter()
        self._first_pts = None
        self._epoch = None
        self._index = 0

    def _offset_of(self, frame: Any) -> float:
        """Where this frame belongs on the run's timeline, in seconds."""
        metadata = getattr(frame, "metadata", None)
        pts = getattr(metadata, "pts", None) if metadata is not None else None
        epoch = getattr(metadata, "stream_epoch", 0) if metadata is not None else 0

        if pts is None:
            return (self._index - 1) * self._interval

        # A reconnect restarts PTS from a new base, so the anchor is re-taken
        # rather than subtracted across the boundary. Without this, the first
        # frame after a reconnect gets a deadline decades away or decades past.
        if self._epoch != epoch or self._first_pts is None:
            self._epoch = epoch
            self._first_pts = pts
            self._t0 = time.perf_counter()
        return pts - self._first_pts

    def read(self) -> Any:
        if self._t0 is None:
            self._t0 = time.perf_counter()

        consecutive = 0
        while True:
            frame = self._inner.read()
            self._index += 1
            if frame is None:
                return None

            deadline = self._t0 + self._offset_of(frame)
            now = time.perf_counter()

            if now > deadline + self._interval:
                if self._recorder is not None:
                    self._recorder.record_drop("behind_schedule")
                consecutive += 1
                if consecutive >= self._max_consecutive_drops:
                    # Not a safety valve for the benchmark — a signal that the
                    # run is worthless. Dropping hundreds in a row means the
                    # pipeline is not merely late, it is not keeping up at all,
                    # and the resulting "drop rate" would understate that.
                    raise RuntimeError(
                        f"[{self.source_id}] dropped {consecutive} frames in a "
                        f"row at {self._fps:.2f} fps. The pipeline is not "
                        f"running behind, it is not running: any drop rate "
                        f"computed from this run describes the test machine."
                    )
                continue

            if now < deadline:
                # Recorded as its own stage. The engine times the whole of
                # read(), so in realtime mode "source_ingest" is mostly this
                # sleep — which is why metrics.py withholds that stage here
                # rather than publishing decode cost that is really a nap.
                time.sleep(deadline - now)
                if self._recorder is not None:
                    self._recorder.record_span("pacing_wait", now, time.perf_counter())
            return frame
