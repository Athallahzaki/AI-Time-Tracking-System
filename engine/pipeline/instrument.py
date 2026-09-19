"""
Measurement seam for the frame loop.

This replaces `vision_core/metrics/performance.py`, which was deliberately NOT
ported. That module kept a 60-sample rolling mean per stage: it cannot produce
the p95 that ARCHITECTURE.md §13 asks for, it has no camera dimension, and —
fatally — it measures each stage as a *synchronous duration inside one loop*.
The moment step 18 moves recognition onto a worker pool, a number called
"latency_recognize_ms" stops meaning anything while still being produced. A
measuring instrument that silently changes meaning is worse than none.

B0 therefore ships only the seam and a recorder that does nothing. B1 plugs in
the span recorder — pushing (stage, camera_id, pts, track_uuid, t_start, t_end)
into a ring buffer, dumped to file, percentiles computed offline — WITHOUT
touching the frame loop again.

Keeping the seam (rather than stripping the calls out of engine.py) is a
zero-effect change: NullRecorder does nothing, so B0 behaves exactly like the
old code minus the rolling averages nobody consumed.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Recorder(Protocol):
    """What the frame loop is allowed to ask of its instrumentation."""

    def record_latency(self, stage: str, duration_ms: float) -> None:
        ...

    def record_frame(self) -> None:
        ...

    def record_drop(self) -> None:
        ...


class NullRecorder:
    """
    Records nothing. The default, and the one B0 uses.

    It keeps two counters only because `VisionEngine.stop()` reports them on
    shutdown; they are not a measurement and must not be used as one.
    """

    __slots__ = ("_frames", "_drops")

    def __init__(self) -> None:
        self._frames = 0
        self._drops = 0

    def record_latency(self, stage: str, duration_ms: float) -> None:
        return None

    def record_frame(self) -> None:
        self._frames += 1

    def record_drop(self) -> None:
        self._drops += 1

    @property
    def total_frames(self) -> int:
        return self._frames

    @property
    def dropped_frames(self) -> int:
        return self._drops

    def summary_str(self) -> str:
        return (
            f"frames={self._frames} drops={self._drops} "
            f"(no timing recorded — see engine/tools/bench in B1)"
        )
