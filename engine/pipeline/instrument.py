"""
Measurement seam for the frame loop.

This replaces `vision_core/metrics/performance.py`, which was deliberately NOT
ported. That module kept a 60-sample rolling mean per stage: it cannot produce
the p95 that ARCHITECTURE.md §13 asks for, it has no camera dimension, and —
fatally — it measured each stage as a *synchronous duration inside one loop*.
The moment step 18 moves recognition onto a worker pool, a number called
"latency_recognize_ms" stops meaning anything while still being produced. A
measuring instrument that silently changes meaning is worse than none.

## What B1 changed here, and why B0's note was wrong

B0 shipped this seam with a single method, `record_latency(stage, duration_ms)`,
and claimed in engine/README.md that B1 would plug a span recorder in "without
touching the frame loop again". That claim was wrong, and it is worth stating
plainly rather than quietly fixing.

A duration is not a span. §13.3 asks for `(stage, camera_id, pts, track_uuid,
t_start, t_end)` precisely so that a stage which later becomes asynchronous
still produces an interval that can be placed on a timeline next to the frame
it belongs to. A recorder handed only `("detector", 4.1)` cannot recover which
camera or which frame that 4.1 ms belongs to, so it cannot be turned into a
span after the fact. The seam had the wrong shape.

So B1 widens it: `begin_frame()` names the frame every subsequent span belongs
to, and `record_span()` carries the interval endpoints instead of their
difference. The change is still zero-effect — `NullRecorder` does nothing under
either shape, and `tests/test_b1_bench.py` asserts the mock pipeline produces
identical track output with and without a recorder attached.

The seam is deliberately dumber than the thing that consumes it: it does no
aggregation, no percentiles, no rolling anything. Aggregation happens offline,
in `engine/bench/metrics.py`, over a dumped file. That is what makes it survive
the refactor in step 18.
"""

from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable


@runtime_checkable
class Recorder(Protocol):
    """
    What the frame loop is allowed to ask of its instrumentation.

    Every method must be cheap and must never raise: instrumentation that can
    break the pipeline it measures is worse than no instrumentation.
    """

    def begin_frame(self, camera_id: str, frame_id: int, pts: float) -> None:
        """Names the frame that subsequent spans belong to."""
        ...

    def record_span(
        self,
        stage: str,
        t_start: float,
        t_end: float,
        track_uuid: Optional[str] = None,
    ) -> None:
        """Records one stage interval, in `time.perf_counter()` units."""
        ...

    def record_frame(self) -> None:
        """One frame completed the loop."""
        ...

    def record_drop(self, reason: str = "unspecified") -> None:
        """One frame was skipped without being processed."""
        ...


class NullRecorder:
    """
    Records nothing. The default, and the one B0 and production use.

    It keeps two counters only because `VisionEngine.stop()` reports them on
    shutdown; they are not a measurement and must not be used as one. Anything
    that needs numbers uses `engine.bench.spans.SpanRecorder`.
    """

    __slots__ = ("_frames", "_drops")

    def __init__(self) -> None:
        self._frames = 0
        self._drops = 0

    def begin_frame(self, camera_id: str, frame_id: int, pts: float) -> None:
        return None

    def record_span(
        self,
        stage: str,
        t_start: float,
        t_end: float,
        track_uuid: Optional[str] = None,
    ) -> None:
        return None

    def record_frame(self) -> None:
        self._frames += 1

    def record_drop(self, reason: str = "unspecified") -> None:
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
            f"(no timing recorded — run python -m engine.bench for that)"
        )
