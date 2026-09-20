"""
The stream timeline: PTS, the wallclock offset, and the epoch boundary.

This module holds everything about time that does *not* need PyAV, which is
almost all of it. `pyav_source.py` is then a thin binding that hands raw
container values here. The split is deliberate: the interesting logic — the
offset rule of §6.6, the reconnect boundary, the deviation measurement — is
fully unit-tested, and the part that cannot be tested without a real decoder is
small enough to read in one sitting.

## Three rules, all from ARCHITECTURE.md §6.6

**PTS is stream-relative, and the container's own value is kept beside it.**
The first version of this module passed the raw container value straight
through and argued, from §6.6, that rebasing destroys the property that the
engine and the backend read *the same number* for the same frame. The argument
is sound and it was applied to the wrong field. `contracts/schema/…` defines
`pts` as "detik, float, RELATIF terhadap awal stream kamera pada `stream_epoch`
yang berlaku", `ENGINE_PROTOCOL.md` §1 repeats it, and `api/events.PtsClock`
computes `at()` as `offset + pts` on exactly that assumption. RTP starts from a
random base, so on a real camera the raw value made every `*_at` wrong by that
base while every `*_pts` still looked plausible — a file starting at PTS 0
hides it completely, which is why the tests and the probe were both happy.

So `pts` now means what the frozen schema says it means, and `container_pts`
carries the unrebased value for anyone who wants §6.6's shared-number property.
Nothing downstream lost information, and no duration changed: subtraction
cancels the base.

**The wallclock offset is set once per epoch, at the first frame.** All interval
arithmetic happens in PTS — precise, no drift — and conversion to absolute time
happens only at the edge, when an event is emitted. §6.6 also warns against
FFmpeg's `-use_wallclock_as_timestamps`, which overwrites PTS with arrival time
and folds network jitter into the timestamp; this module never does that.

**The offset is re-established on every reconnect.** RTP starts from a fresh
random offset, so a new connection is a new timeline. §6.6 calls this one line
of code that, if missed, makes every camera that ever dropped report intervals
in the wrong year — and only that camera. There is a second consequence the
document does not spell out: after a reconnect PTS can go *backwards*, and any
code that subtracts two PTS values must know they are from different epochs or
it produces a duration that is not wrong so much as meaningless. Hence
`stream_epoch`, which every consumer is expected to compare before subtracting
(`epochs_are_comparable` below is that comparison, and it is called rather than
re-implemented: a rule spelled out in four places is a rule with four chances to
be spelled differently).

## The offset is a number, and it leaves this module as one

§4.4 and §4.5 of the protocol put `pts_wallclock_offset` on the wire, per camera
per epoch, and the conformance checklist in §7 requires it to be re-established
on every reconnect. The first version computed the offset internally, added it
to the frame's wallclock and then threw the addend away, so the only layer that
had to emit the number had no way to obtain it and reached for `time.time()`
instead. Both halves were internally consistent and their sum was wrong. Hence
`wallclock_offset`, which is exactly the value satisfying
`wallclock == offset + pts`.

## On anomalies: count, do not crash

Within one epoch PTS should never go backwards. If it does, an assumption here
is wrong, and this module says so — but by counting and reporting, not by
raising. A 24/7 RTSP stream that dies on one malformed timestamp is a worse
failure than a run with three counted anomalies in its report. The rule this
codebase actually holds is *never degrade silently*; counted and printed is not
silent.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("engine.ingest.timeline")

PTS_CONTAINER = "container"
PTS_DERIVED = "derived_from_fps"
PTS_NONE = "none"


@dataclass(frozen=True)
class Stamp:
    """
    One frame's position in time, in the three forms anyone needs.

    Returned as an object rather than a tuple because the two PTS values differ
    by a base that is zero in every test file and arbitrary on every real
    camera. A tuple invites unpacking them in the wrong order, and the failure
    would be invisible on a file and confined to reconnected cameras in
    production — the single worst shape a bug can have in this codebase.
    """

    pts: Optional[float]
    """Seconds since the start of this epoch's stream. What the schema calls `pts`."""

    container_pts: Optional[float]
    """The container's own value, unrebased. §6.6's shared-number property."""

    wallclock: Optional[float]
    """Absolute time: `offset + pts`."""

    offset: Optional[float]
    """
    The epoch's `pts_wallclock_offset` (§4.5). Re-established on every
    reconnect, and the value the wire field must carry.
    """


@dataclass
class StreamTimeline:
    """
    Per-source timeline state. One instance per open stream, surviving
    reconnects so the epoch counter keeps climbing.
    """

    source_id: str = "default"
    epoch: int = 0

    _epoch_first_pts: Optional[float] = None
    _epoch_wall_start: Optional[float] = None
    _last_pts: Optional[float] = None
    _backwards: int = 0
    _epochs_opened: int = 0
    _frames_in_epoch: int = 0

    def begin_epoch(self, wall_now: Optional[float] = None) -> int:
        """
        Called on every successful open, including reconnects.

        Returns the new epoch number. The offset is not fixed here but at the
        first frame of the epoch, because the first frame's PTS is what it has
        to be anchored to and it has not arrived yet.
        """
        if self._epochs_opened:
            self.epoch += 1
            logger.info(
                "[%s] stream reconnected: epoch %d. PTS restarts from a new "
                "base; durations must not be computed across this boundary.",
                self.source_id,
                self.epoch,
            )
        self._epochs_opened += 1
        self._epoch_first_pts = None
        self._epoch_wall_start = wall_now if wall_now is not None else time.time()
        self._last_pts = None
        self._frames_in_epoch = 0
        return self.epoch

    def stamp(self, raw_pts: Optional[float]) -> Stamp:
        """
        Turns one container PTS into a `Stamp`.

        The first frame of an epoch defines the base, so `pts` starts at 0.0 for
        every epoch — which is what the schema requires and what makes
        `PtsClock.at()` correct without knowing anything about RTP.
        """
        self._frames_in_epoch += 1

        if raw_pts is None:
            return Stamp(None, None, None, self.wallclock_offset)

        if self._epoch_first_pts is None:
            self._epoch_first_pts = raw_pts

        if self._last_pts is not None and raw_pts < self._last_pts:
            self._backwards += 1
            if self._backwards == 1:
                logger.warning(
                    "[%s] PTS went backwards within epoch %d (%.6f after "
                    "%.6f). Counted, not fatal — the count is reported. If it "
                    "is more than a handful, the timeline is not trustworthy.",
                    self.source_id,
                    self.epoch,
                    raw_pts,
                    self._last_pts,
                )
        self._last_pts = raw_pts

        pts = raw_pts - self._epoch_first_pts
        # Guards the schema's `minimum: 0` rather than trusting it. A PTS below
        # the epoch base can only come from a stream whose first frame was not
        # its earliest, and a negative pts makes `PtsClock.at()` raise in the
        # event layer — far from here, where the cause is no longer visible.
        if pts < 0.0:
            pts = 0.0

        offset = self.wallclock_offset
        wall = None if offset is None else offset + pts
        return Stamp(pts=pts, container_pts=raw_pts, wallclock=wall, offset=offset)

    @property
    def wallclock_offset(self) -> Optional[float]:
        """
        This epoch's `pts_wallclock_offset`: the value where `wallclock == offset + pts`.

        Because `pts` is now stream-relative, the offset is simply the epoch's
        wall start — no subtraction of a container base, and nothing for a
        caller to reconstruct.
        """
        return self._epoch_wall_start

    @property
    def epoch_base_pts(self) -> Optional[float]:
        """The container PTS the current epoch was anchored to. Diagnostics only."""
        return self._epoch_first_pts

    @property
    def backwards_count(self) -> int:
        return self._backwards

    @property
    def epochs_opened(self) -> int:
        return self._epochs_opened

    def as_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "epoch": self.epoch,
            "epochs_opened": self._epochs_opened,
            "pts_backwards_within_epoch": self._backwards,
            # On the wire this is `pts_wallclock_offset` (§4.4, §4.5). In the
            # report it is here so that a recorded run can be re-derived into
            # absolute time months later, when nobody remembers what time it
            # started.
            "pts_wallclock_offset": self.wallclock_offset,
            "epoch_base_container_pts": self._epoch_first_pts,
        }


def derived_pts(frame_index: int, fps: float) -> Optional[float]:
    """
    `(frame_index - 1) / fps`, the only timeline `cv2.VideoCapture` allows.

    Exact for a constant-rate file. For a variable-rate one it assumes frames
    that were never recorded, and the error accumulates locally even when the
    average rate is right.
    """
    if fps <= 0.0:
        return None
    return (frame_index - 1) / fps


# ---------------------------------------------------------------------------
# How far the assumed timeline is from the real one
# ---------------------------------------------------------------------------

@dataclass
class TimelineFidelity:
    """
    Measures `derived_pts` against real container PTS, frame by frame.

    This is what settles, rather than assumes, whether the B1-era timeline was
    good enough. Four statistics; read the last one.

    **`max_abs_deviation`** — the worst single moment: how far apart the two
    clocks ever get. Useful for understanding the shape, and **not** the number
    to judge on. An earlier version of this docstring claimed it was the one
    that matters for gaps. It is not, and the first real recording proved it.

    **`rms_deviation`** — the typical error. A small RMS with a large max means
    the timeline is fine except in a few places, which is precisely the shape a
    phone dropping frames in dark stretches produces.

    **`final_drift`** — where the two timelines end up after the whole file. A
    near-zero final drift with a non-zero max is the signature everyone
    misreads as "the fps was right": the *average* rate was right and the
    instantaneous one was not.

    **`interval_error`** — and this is the one that actually matters, which the
    first version of this class did not report. `max_abs_deviation` answers
    "how far apart are the two clocks at the worst moment". Nobody needs that.
    Every product metric here is a *duration* — a gap, a track lifetime — and a
    duration is a difference of two instants, so what it inherits is the
    difference of two deviations, not their level.

    The distinction is not academic. On the first real recording the deviation
    reached 0.80 s, which reads as alarming, and yet the error on a twelve
    second gap in the same stretch was 0.097 s — because the deviation was a
    slow linear ramp and a ramp almost cancels across a short window. The
    damage was concentrated in two stalls where the ramp stepped; a gap
    spanning one of those is wrong by the whole step.

    So `interval_error[w]` is the largest amount by which any duration of up to
    `w` seconds can be misstated: the maximum spread of the deviation inside
    any sliding window of that width. Read that number, not the maximum
    deviation.
    """

    samples: int = 0
    _sum_sq: float = 0.0
    _max_abs: float = 0.0
    _last_deviation: float = 0.0
    _max_at_pts: Optional[float] = None
    _gaps_over_nominal: int = 0
    _nominal_interval: Optional[float] = None
    _prev_pts: Optional[float] = None
    # (pts, deviation) per frame, for the sliding-window analysis below. A
    # half-hour 25 fps run is 45k pairs; the stride keeps a very long run from
    # turning the measurement into its own memory problem.
    _series: List[Tuple[float, float]] = field(default_factory=list)
    _stride: int = 1
    _series_cap: int = 200_000

    def set_nominal_fps(self, fps: float) -> None:
        self._nominal_interval = (1.0 / fps) if fps > 0 else None

    def observe(self, frame_index: int, real_pts: float, fps: float) -> None:
        assumed = derived_pts(frame_index, fps)
        if assumed is None:
            return
        deviation = real_pts - assumed
        self.samples += 1
        self._sum_sq += deviation * deviation
        self._last_deviation = deviation
        if abs(deviation) > self._max_abs:
            self._max_abs = abs(deviation)
            self._max_at_pts = real_pts

        # A frame interval longer than 1.5x nominal means the recorder skipped.
        # Counting them locates the variable-rate behaviour instead of implying
        # it from an average.
        if self._nominal_interval and self._prev_pts is not None:
            if (real_pts - self._prev_pts) > 1.5 * self._nominal_interval:
                self._gaps_over_nominal += 1
        self._prev_pts = real_pts

        if self.samples % self._stride == 0:
            self._series.append((real_pts, deviation))
            if len(self._series) > self._series_cap:
                # Halve the resolution rather than stop recording: a truncated
                # series would silently describe only the beginning of the run.
                self._series = self._series[::2]
                self._stride *= 2

    def interval_error(
        self, windows: Sequence[float] = (1.0, 5.0, 30.0, 300.0)
    ) -> Dict[str, Optional[float]]:
        """
        The largest amount by which a duration of up to `w` seconds can be wrong.

        Maximum spread of the deviation inside any sliding window of width `w`.
        Linear-time per window with monotonic deques, which matters because the
        series is one entry per frame.
        """
        from collections import deque

        out: Dict[str, Optional[float]] = {}
        series = self._series
        for window in windows:
            key = f"<={window:g}s"
            if len(series) < 2:
                out[key] = None
                continue
            highs: Any = deque()
            lows: Any = deque()
            left = 0
            worst = 0.0
            for right, (pts, dev) in enumerate(series):
                while highs and series[highs[-1]][1] <= dev:
                    highs.pop()
                highs.append(right)
                while lows and series[lows[-1]][1] >= dev:
                    lows.pop()
                lows.append(right)
                while series[right][0] - series[left][0] > window:
                    if highs[0] == left:
                        highs.popleft()
                    if lows[0] == left:
                        lows.popleft()
                    left += 1
                spread = series[highs[0]][1] - series[lows[0]][1]
                if spread > worst:
                    worst = spread
            out[key] = round(worst, 6)
        return out

    def as_dict(self) -> Dict[str, Any]:
        if not self.samples:
            return {
                "samples": 0,
                "max_abs_deviation_s": None,
                "rms_deviation_s": None,
                "final_drift_s": None,
                "interval_error_s": None,
                "long_frame_intervals": None,
                "verdict": "not measured",
            }
        rms = math.sqrt(self._sum_sq / self.samples)
        intervals = self.interval_error()
        return {
            "samples": self.samples,
            "interval_error_s": intervals,
            "series_stride": self._stride,
            "max_abs_deviation_s": round(self._max_abs, 6),
            "max_deviation_at_pts_s": (
                None if self._max_at_pts is None else round(self._max_at_pts, 4)
            ),
            "rms_deviation_s": round(rms, 6),
            "final_drift_s": round(self._last_deviation, 6),
            "long_frame_intervals": self._gaps_over_nominal,
            "verdict": self._verdict(rms, intervals),
        }

    def _verdict(self, rms: float, intervals: Dict[str, Optional[float]]) -> str:
        """
        Plain words, because this number will be read by someone deciding
        whether an old baseline is still comparable.
        """
        # The verdict is taken from the interval error, not the deviation. A
        # large deviation that is a slow ramp barely affects any duration; a
        # small deviation that steps does. Judging on the level rather than the
        # spread was the first version's mistake and it would have condemned a
        # perfectly usable recording.
        thirty = intervals.get("<=30s")
        five = intervals.get("<=5s")
        worst = max(v for v in (thirty, five, 0.0) if v is not None)

        if worst < 0.010:
            return (
                "usable as-is: no duration up to 30 s can be wrong by more "
                "than 10 ms on the derived timeline, so pre-B4 numbers from "
                "this recording are comparable with post-B4 ones"
            )
        if worst < 0.200:
            return (
                f"mildly variable: a duration of up to 30 s can be misstated "
                f"by {worst*1000:.0f} ms. Harmless for track lifetime; worth "
                f"knowing when a gap is being argued over to the second"
            )
        return (
            f"variable rate: a duration of up to 30 s can be misstated by "
            f"{worst:.2f} s on the derived timeline. Measure this recording "
            f"with ingest.backend: pyav, and do not compare gap lengths taken "
            f"on the two timelines"
        )


def epochs_are_comparable(epoch_a: int, epoch_b: int) -> bool:
    """
    Whether two PTS values may be subtracted.

    Called before every duration computation that spans two frames. A reconnect
    resets the stream's timebase, so a subtraction across it yields a number
    with no meaning — and, being a float, it prints perfectly well.
    """
    return epoch_a == epoch_b


def split_on_epoch_change(
    records: Sequence[Tuple[int, float]],
) -> List[List[Tuple[int, float]]]:
    """Splits a sequence of `(epoch, pts)` into runs of one epoch each."""
    runs: List[List[Tuple[int, float]]] = []
    current: List[Tuple[int, float]] = []
    last_epoch: Optional[int] = None
    for epoch, pts in records:
        if last_epoch is not None and epoch != last_epoch:
            runs.append(current)
            current = []
        current.append((epoch, pts))
        last_epoch = epoch
    if current:
        runs.append(current)
    return runs
