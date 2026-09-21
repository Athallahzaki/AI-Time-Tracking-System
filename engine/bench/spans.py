"""
Span recording: intervals, not averages.

ARCHITECTURE.md §13.3. Each stage pushes `(stage, camera_id, pts, track_uuid,
t_start, t_end)` into a ring buffer; the file is dumped at the end and
percentiles are computed offline. Nothing here aggregates, because an
aggregation that lives next to the frame loop is an aggregation that keeps
producing numbers after the thing it measures stops being synchronous.

Two honesty mechanisms are worth reading before trusting a latency number.

**Exact counts, sampled percentiles.** The ring buffer is bounded, because a
half-hour five-camera run produces millions of spans and an unbounded list
would put the benchmark's own memory pressure into the measurement. When it
wraps, older spans are evicted — so percentiles would silently describe only
the tail of the run. The recorder therefore keeps an exact count, sum, min and
max per stage *outside* the ring: means are always exact over every span, and
the report marks percentiles as `tail_only` the moment a single span is
evicted. A percentile computed over an unannounced suffix is the sort of number
that looks fine for months.

**One recorder per camera.** No locks, no shared state, nothing to contend on.
Aggregation across cameras happens offline in `metrics.py`, after the run.
"""

from __future__ import annotations

import json
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Deque, Dict, Iterable, Iterator, List, Optional, Tuple

# A span is stored as a plain tuple rather than a dataclass: at a few hundred
# thousand of them, the attribute machinery is not free and this object is
# created inside the loop being measured.
#   (stage, frame_id, pts, t_start, t_end, track_uuid)
SpanTuple = Tuple[str, int, float, float, float, Optional[str]]

DEFAULT_RING_CAPACITY = 500_000


@dataclass
class StageTotals:
    """Exact aggregates, kept outside the ring so eviction cannot distort them."""

    count: int = 0
    total_ms: float = 0.0
    min_ms: float = float("inf")
    max_ms: float = 0.0

    def add(self, duration_ms: float) -> None:
        self.count += 1
        self.total_ms += duration_ms
        if duration_ms < self.min_ms:
            self.min_ms = duration_ms
        if duration_ms > self.max_ms:
            self.max_ms = duration_ms

    def as_dict(self) -> Dict[str, float]:
        return {
            "count": self.count,
            "mean_ms": (self.total_ms / self.count) if self.count else 0.0,
            "min_ms": 0.0 if self.min_ms == float("inf") else self.min_ms,
            "max_ms": self.max_ms,
        }


class SpanRecorder:
    """
    Satisfies `pipeline.instrument.Recorder`. One per camera.

    Every method must be cheap and must never raise — this runs inside the loop
    it measures.
    """

    __slots__ = (
        "camera_id",
        "_ring",
        "_capacity",
        "_evicted",
        "_totals",
        "_frames",
        "_drops",
        "_drop_reasons",
        "_frame_id",
        "_pts",
        "_t_first",
        "_t_last",
    )

    def __init__(self, camera_id: str, capacity: int = DEFAULT_RING_CAPACITY) -> None:
        self.camera_id = camera_id
        self._capacity = capacity
        self._ring: Deque[SpanTuple] = deque(maxlen=capacity)
        self._evicted = 0
        self._totals: Dict[str, StageTotals] = {}
        self._frames = 0
        self._drops = 0
        self._drop_reasons: Dict[str, int] = {}
        self._frame_id = 0
        self._pts = 0.0
        self._t_first: Optional[float] = None
        self._t_last: Optional[float] = None

    # -- Recorder ---------------------------------------------------------

    def begin_frame(self, camera_id: str, frame_id: int, pts: float) -> None:
        self._frame_id = frame_id
        self._pts = pts

    def record_span(
        self,
        stage: str,
        t_start: float,
        t_end: float,
        track_uuid: Optional[str] = None,
    ) -> None:
        if len(self._ring) == self._capacity:
            self._evicted += 1
        self._ring.append((stage, self._frame_id, self._pts, t_start, t_end, track_uuid))

        totals = self._totals.get(stage)
        if totals is None:
            totals = self._totals[stage] = StageTotals()
        totals.add((t_end - t_start) * 1000.0)

        if self._t_first is None:
            self._t_first = t_start
        self._t_last = t_end

    def record_frame(self) -> None:
        self._frames += 1

    def record_drop(self, reason: str = "unspecified") -> None:
        self._drops += 1
        self._drop_reasons[reason] = self._drop_reasons.get(reason, 0) + 1

    # -- results ----------------------------------------------------------

    @property
    def total_frames(self) -> int:
        return self._frames

    @property
    def dropped_frames(self) -> int:
        return self._drops

    @property
    def evicted_spans(self) -> int:
        return self._evicted

    @property
    def drop_reasons(self) -> Dict[str, int]:
        return dict(self._drop_reasons)

    @property
    def wall_seconds(self) -> float:
        """Wall time from the first span to the last, in seconds."""
        if self._t_first is None or self._t_last is None:
            return 0.0
        return max(0.0, self._t_last - self._t_first)

    def totals(self) -> Dict[str, StageTotals]:
        return dict(self._totals)

    def durations_ms(self) -> Dict[str, List[float]]:
        """Per-stage durations of the spans still in the ring."""
        out: Dict[str, List[float]] = {}
        for stage, _fid, _pts, t0, t1, _uuid in self._ring:
            out.setdefault(stage, []).append((t1 - t0) * 1000.0)
        return out

    def summary_str(self) -> str:
        return (
            f"frames={self._frames} drops={self._drops} "
            f"spans={len(self._ring)} evicted={self._evicted}"
        )

    def write_ndjson(self, path: Path, t_zero: Optional[float] = None) -> int:
        """
        Dumps retained spans. `t_zero` rebases perf_counter values so separate
        camera files share one timeline.
        """
        base = t_zero if t_zero is not None else 0.0
        path.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        with path.open("w", encoding="utf-8") as handle:
            for stage, frame_id, pts, t0, t1, track_uuid in self._ring:
                handle.write(
                    json.dumps(
                        {
                            "cam": self.camera_id,
                            "stage": stage,
                            "f": frame_id,
                            "pts": round(pts, 4),
                            "t0": round(t0 - base, 6),
                            "t1": round(t1 - base, 6),
                            "ms": round((t1 - t0) * 1000.0, 4),
                            "track_uuid": track_uuid,
                        },
                        separators=(",", ":"),
                    )
                )
                handle.write("\n")
                written += 1
        return written


def read_ndjson(path: Path) -> Iterator[dict]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def now() -> float:
    return time.perf_counter()
