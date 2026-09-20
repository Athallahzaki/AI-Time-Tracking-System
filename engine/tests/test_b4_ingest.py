"""
Acceptance tests for B4 — PyAV ingest and a real timeline.

PyAV could not be installed in the environment this step was written in, so the
binding is driven here by a fake container that behaves the way libav is
documented to. That covers the logic: PTS conversion, the wallclock offset, the
reconnect epoch, the frame-count fallback, the variable-rate measurement. What
it cannot cover is whether real PyAV matches the fake — which is what
`python -m engine.tools.probe_ingest` exists to settle on a real file, and why
that tool is the first thing to run after unpacking this step.

The scenario numbers below come from the real test recording, because a fake
built from a plausible-sounding guess proves less than one built from a file
that exists: 1920x1080 HEVC, 109.32 s, r_frame_rate 25 against avg_frame_rate
67775/2733 — which is 2711 frames where a constant 25 fps would have produced
2733. Twenty-two frames that were never recorded, and that `index / fps`
silently assumes into the timeline.
"""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest

from engine.bench import metrics as M
from engine.ingest.timeline import (
    PTS_CONTAINER,
    PTS_DERIVED,
    StreamTimeline,
    TimelineFidelity,
    derived_pts,
)

ENGINE_ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------
# A fake libav
# --------------------------------------------------------------------------

class FakeVideoFrame:
    def __init__(self, pts: int, width: int = 64, height: int = 48) -> None:
        self.pts = pts
        self._width = width
        self._height = height

    @property
    def time(self):  # PyAV exposes this; we prefer pts * time_base
        return None

    def to_ndarray(self, format: str = "bgr24"):
        assert format == "bgr24"
        return np.zeros((self._height, self._width, 3), dtype=np.uint8)


class FakeStream:
    def __init__(
        self,
        pts_ticks,
        time_base=Fraction(1, 90000),
        width=64,
        height=48,
        frames=0,
        duration=None,
        average_rate=Fraction(24799, 1000),
        guessed_rate=Fraction(25, 1),
    ) -> None:
        self.pts_ticks = list(pts_ticks)
        self.time_base = time_base
        self.width = width
        self.height = height
        self.frames = frames
        self.duration = duration
        self.average_rate = average_rate
        self.guessed_rate = guessed_rate
        self.thread_type = None


class _Streams:
    def __init__(self, stream):
        self.video = [stream]


class FakeContainer:
    def __init__(self, stream: FakeStream, duration=None) -> None:
        self.streams = _Streams(stream)
        self.duration = duration
        self.closed = False
        self._stream = stream

    def decode(self, stream):
        for tick in self._stream.pts_ticks:
            yield FakeVideoFrame(tick, stream.width, stream.height)

    def close(self):
        self.closed = True


class FakeAv:
    """Hands out a scripted container per `open()`, so reconnects differ."""

    codecs_available = ["h264", "hevc", "aac"]
    __version__ = "fake"

    def __init__(self, containers, fail_after=None) -> None:
        self._containers = list(containers)
        self.opens = 0
        self.options_seen = []
        self._fail_after = fail_after

    def open(self, uri, options=None, **kwargs):
        self.opens += 1
        self.options_seen.append(dict(options or {}))
        if self._fail_after is not None and self.opens > self._fail_after:
            raise RuntimeError("connection refused")
        if self.opens > len(self._containers):
            # The script ran out: the camera is gone for good. Handing back the
            # last container again would let the source reconnect for ever and
            # the test would hang instead of failing.
            raise RuntimeError("connection refused")
        return self._containers[self.opens - 1]


def _ticks_at(fps: float, count: int, time_base=Fraction(1, 90000), start=0):
    """Perfectly constant-rate PTS ticks."""
    per_frame = float(time_base.denominator) / fps / float(time_base.numerator)
    return [int(round(start + i * per_frame)) for i in range(count)]


def _source(av, uri="file.mp4", **kwargs):
    from engine.ingest.pyav_source import PyAVSource

    return PyAVSource(uri=uri, av_module=av, **kwargs)


# --------------------------------------------------------------------------
# PTS comes through, and says where it came from
# --------------------------------------------------------------------------

def test_pts_is_the_container_value_not_a_frame_index():
    ticks = [0, 3600, 7200, 12000]     # deliberately NOT evenly spaced
    av = FakeAv([FakeContainer(FakeStream(ticks))])
    source = _source(av)
    source.start()

    seen = []
    while True:
        frame = source.read()
        if frame is None:
            break
        seen.append(frame.metadata.pts)
    source.stop()

    assert seen == [0.0, 0.04, 0.08, pytest.approx(0.13333, rel=1e-4)]


def test_frames_are_labelled_as_carrying_a_real_timeline():
    av = FakeAv([FakeContainer(FakeStream([0, 3600]))])
    source = _source(av)
    source.start()
    frame = source.read()
    source.stop()
    assert frame.metadata.pts_source == PTS_CONTAINER
    assert frame.metadata.has_real_pts is True


def test_the_opencv_file_source_labels_its_timeline_as_derived():
    """
    The point of `pts_source` is that a later reader cannot mistake one for the
    other. Both sources fill `pts`; only one of them earned it.
    """
    from engine.ingest.video_file import VideoFileSource

    clip = ENGINE_ROOT / "samples" / "synthetic_24fps.mp4"
    source = VideoFileSource(filepath=str(clip), realtime_pacing=False)
    source.start()
    frame = source.read()
    source.stop()

    assert frame.metadata.pts_source == PTS_DERIVED
    assert frame.metadata.has_real_pts is False


def test_wallclock_is_anchored_once_and_advances_with_pts():
    av = FakeAv([FakeContainer(FakeStream([0, 90000, 180000]))])
    source = _source(av)
    source.start()
    first = source.read()
    second = source.read()
    third = source.read()
    source.stop()

    # One second of PTS is one second of wallclock, whatever the machine did in
    # between. §6.6: the arithmetic stays in PTS and only the edge converts.
    assert second.metadata.wallclock - first.metadata.wallclock == pytest.approx(1.0)
    assert third.metadata.wallclock - first.metadata.wallclock == pytest.approx(2.0)


# --------------------------------------------------------------------------
# The measurement that justifies this whole step
# --------------------------------------------------------------------------

def test_a_constant_rate_file_shows_no_deviation():
    fidelity = TimelineFidelity()
    fidelity.set_nominal_fps(25.0)
    for index in range(1, 500):
        fidelity.observe(index, (index - 1) / 25.0, 25.0)

    result = fidelity.as_dict()
    assert result["max_abs_deviation_s"] == pytest.approx(0.0, abs=1e-9)
    assert result["interval_error_s"]["<=30s"] == pytest.approx(0.0, abs=1e-9)
    assert "usable as-is" in result["verdict"]


def test_a_recorder_that_skips_frames_shows_up_as_local_deviation():
    """
    The real clip is 2711 frames where 25 fps for 109.32 s would be 2733. If
    those 22 missing frames are clustered rather than spread, the derived
    timeline is locally wrong by nearly a second — in the dark stretch where
    the detector is also losing people. That correlation is the reason B4 was
    moved ahead of the baseline.
    """
    fidelity = TimelineFidelity()
    fidelity.set_nominal_fps(25.0)

    real_pts = 0.0
    avg_fps = 2711 / 109.32       # what cv2 reports: 24.799...
    for index in range(1, 2712):
        fidelity.observe(index, real_pts, avg_fps)
        # 22 frames dropped in one burst a third of the way in.
        real_pts += 0.04 * (23 if index == 900 else 1)

    result = fidelity.as_dict()
    assert result["max_abs_deviation_s"] > 0.2
    assert result["long_frame_intervals"] == 1
    assert "variable rate" in result["verdict"]
    # And the trap: the average rate is right, so the file *ends* almost
    # exactly where the derived timeline predicted.
    assert abs(result["final_drift_s"]) < 0.05


def test_derived_pts_needs_a_positive_fps():
    assert derived_pts(5, 0.0) is None
    assert derived_pts(5, 25.0) == pytest.approx(0.16)


# --------------------------------------------------------------------------
# Reconnect: the epoch boundary
# --------------------------------------------------------------------------

def test_reconnect_bumps_the_epoch_and_reanchors_the_clock():
    """
    RTP restarts from a fresh random base. Without an epoch, the first frame
    after a reconnect produces a duration of several decades that prints
    perfectly well.
    """
    first = FakeContainer(FakeStream([0, 90000]))
    # Second connection starts at a completely unrelated RTP base.
    second = FakeContainer(FakeStream([4_000_000_000, 4_000_090_000]))
    av = FakeAv([first, second])

    source = _source(av, uri="rtsp://camera/stream", reconnect_attempts=1,
                     reconnect_backoff_seconds=0.0)
    source.start()

    frames = []
    while True:
        frame = source.read()
        if frame is None:
            break
        frames.append(frame)
    source.stop()

    assert len(frames) == 4
    assert [f.metadata.stream_epoch for f in frames] == [0, 0, 1, 1]
    # Three opens, not two: the initial one, the reconnect, and one more
    # attempt when the second connection also ends — which the fake refuses.
    # That last one is the path that proves the source gives up instead of
    # reconnecting for ever.
    assert av.opens == 3

    # Inside the new epoch the wallclock is sane again: one second of PTS is
    # one second, and the epoch's anchor absorbed the 12-hour PTS jump.
    delta = frames[3].metadata.wallclock - frames[2].metadata.wallclock
    assert delta == pytest.approx(1.0)


def test_a_file_never_reconnects():
    """End of file is end of file. Retrying would turn a truncated recording
    into a loop that looks like progress."""
    av = FakeAv([FakeContainer(FakeStream([0, 3600]))])
    source = _source(av, uri="room.mp4", reconnect_attempts=5)
    source.start()
    assert source.read() is not None
    assert source.read() is not None
    assert source.read() is None
    source.stop()
    assert av.opens == 1


def test_reconnect_gives_up_and_says_so():
    av = FakeAv([FakeContainer(FakeStream([0]))], fail_after=1)
    source = _source(
        av,
        uri="rtsp://camera/stream",
        reconnect_attempts=2,
        reconnect_backoff_seconds=0.0,
    )
    source.start()
    assert source.read() is not None
    assert source.read() is None      # exhausted, not hanging
    source.stop()


def test_rtsp_gets_tcp_and_a_timeout():
    """
    §5.5 calls both practically mandatory: UDP hands back corrupted frames that
    ruin an embedding without raising, and a camera that dies without a timeout
    hangs the thread for ever.
    """
    av = FakeAv([FakeContainer(FakeStream([0]))])
    source = _source(av, uri="rtsp://camera/stream", timeout_seconds=4.0)
    source.start()
    source.stop()

    options = av.options_seen[0]
    assert options["rtsp_transport"] == "tcp"
    # Both spellings, because ffmpeg renamed it and which one is honoured
    # depends on the build.
    assert options["stimeout"] == "4000000"
    assert options["timeout"] == "4000000"


def test_a_local_file_gets_no_rtsp_options():
    av = FakeAv([FakeContainer(FakeStream([0]))])
    source = _source(av, uri="room.mp4")
    source.start()
    source.stop()
    assert av.options_seen[0] == {}


def test_pts_going_backwards_inside_an_epoch_is_counted_not_raised():
    """
    A live stream that dies on one malformed timestamp is a worse outcome than
    a run whose report says "three anomalies". The rule is never to degrade
    *silently*; counted and printed is not silent.
    """
    timeline = StreamTimeline(source_id="cam0")
    timeline.begin_epoch()
    timeline.stamp(10.0)
    timeline.stamp(9.5)
    timeline.stamp(11.0)
    assert timeline.backwards_count == 1
    assert timeline.as_dict()["pts_backwards_within_epoch"] == 1


# --------------------------------------------------------------------------
# The frame count the truncation check depends on
# --------------------------------------------------------------------------

def test_frame_count_falls_back_to_duration_times_rate():
    """
    `stream.frames` is 0 for many containers and for every live stream, and the
    truncated-run check in streams/local.py depends on this number. Silence
    there would quietly disable a check that exists to stop a 6% run being
    reported as a full one.
    """
    stream = FakeStream(
        [0, 3600],
        frames=0,
        duration=int(109.32 * 90000),
        average_rate=Fraction(2711, 10932) * 100,
    )
    av = FakeAv([FakeContainer(stream)])
    source = _source(av)
    source.start()
    total = source.total_frames
    source.stop()

    assert total == pytest.approx(2711, abs=2)


def test_a_declared_frame_count_is_preferred_over_the_estimate():
    stream = FakeStream([0, 3600], frames=2711, duration=int(109.32 * 90000))
    av = FakeAv([FakeContainer(stream)])
    source = _source(av)
    source.start()
    assert source.total_frames == 2711
    source.stop()


# --------------------------------------------------------------------------
# Nothing downstream may compute across an epoch
# --------------------------------------------------------------------------

def _epoch_log(tmp_path: Path) -> Path:
    import json

    path = tmp_path / "tracks_cam0.ndjson"
    lines = []
    for pts in (0.0, 0.1, 0.2):
        lines.append(
            json.dumps({"cam": "cam0", "f": 1, "pts": pts, "e": 0, "w": 64, "h": 48,
                        "tr": [[1, 0.1, 0.1, 0.2, 0.5, "TRACKED", 0.9]]})
        )
    # After a reconnect: same track id, PTS on a new base that happens to look
    # like a tiny forward step.
    for pts in (0.25, 0.35):
        lines.append(
            json.dumps({"cam": "cam0", "f": 1, "pts": pts, "e": 1, "w": 64, "h": 48,
                        "tr": [[1, 0.1, 0.1, 0.2, 0.5, "TRACKED", 0.9]]})
        )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def test_a_reconnect_always_ends_a_segment(tmp_path):
    from engine.bench.tracklog import segments_from_log

    segments = segments_from_log(_epoch_log(tmp_path), max_gap_seconds=0.5)
    assert len(segments) == 2, [s.as_dict() for s in segments]
    assert [s.epoch for s in segments] == [0, 1]


def test_stitching_refuses_to_cross_an_epoch(tmp_path):
    """
    The gap here is 0.05 s — well inside every stitching window. It must still
    not be stitched, because the two numbers are on different timebases and
    their difference means nothing.
    """
    from engine.bench.tracklog import segments_from_log

    segments = segments_from_log(_epoch_log(tmp_path), max_gap_seconds=0.5)
    chains, _basis = M.stitch(segments, window_seconds=30.0, annotation=None)
    assert len(chains) == 2


def test_old_track_logs_without_an_epoch_field_still_load(tmp_path):
    """Additive-only (§13.4): a log written before B4 has no `e` and must read
    as epoch 0 rather than failing."""
    import json

    from engine.bench.tracklog import segments_from_log

    path = tmp_path / "tracks_cam0.ndjson"
    path.write_text(
        json.dumps({"cam": "cam0", "f": 1, "pts": 0.0, "w": 64, "h": 48,
                    "tr": [[1, 0.1, 0.1, 0.2, 0.5, "TRACKED", 0.9]]}),
        encoding="utf-8",
    )
    segments = segments_from_log(path)
    assert segments[0].epoch == 0


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

def test_the_ingest_section_is_accepted(tmp_path):
    from engine.config import load_config

    path = tmp_path / "c.yaml"
    path.write_text(
        "core:\n  source_type: mock\ningest:\n  backend: opencv\n"
        "  reconnect_attempts: 3\n",
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.ingest.backend == "opencv"
    assert config.ingest.reconnect_attempts == 3


def test_an_unknown_ingest_key_is_refused(tmp_path):
    from engine.config import ConfigBoundaryError, load_config

    path = tmp_path / "c.yaml"
    path.write_text("core:\n  source_type: mock\ningest:\n  backendd: pyav\n", "utf-8")
    with pytest.raises(ConfigBoundaryError, match="backendd"):
        load_config(path)


def test_an_unknown_ingest_backend_is_refused():
    from engine.config import IngestConfig

    with pytest.raises(ValueError, match="Unknown ingest backend"):
        IngestConfig(backend="gstreamer")


def test_the_shipped_config_defaults_to_the_real_timeline():
    from engine.config import load_config

    assert load_config().ingest.backend == "pyav"


# --------------------------------------------------------------------------
# The report says which timeline it used
# --------------------------------------------------------------------------

def test_timeline_fidelity_is_withheld_for_the_opencv_backend():
    summary = M.timeline_summary(
        [{"camera_id": "cam0", "pts_source": "derived_from_fps", "extra": {}}]
    )
    assert summary["fidelity"]["value"] is None
    assert "no container PTS" in summary["fidelity"]["withheld_reason"]


def test_timeline_summary_reports_the_worst_camera_not_the_average():
    """
    The question is "could any duration in this report be wrong", not "is it
    usually fine". Averaging the deviation across cameras would answer the
    second while looking like the first.
    """
    summary = M.timeline_summary(
        [
            {
                "camera_id": "cam0",
                "pts_source": "container",
                "extra": {"timeline_fidelity": {"max_abs_deviation_s": 0.004}},
            },
            {
                "camera_id": "cam1",
                "pts_source": "container",
                "extra": {"timeline_fidelity": {"max_abs_deviation_s": 0.91}},
            },
        ]
    )
    assert summary["fidelity"]["max_abs_deviation_s"] == 0.91


def test_timeline_summary_counts_reconnects():
    summary = M.timeline_summary(
        [
            {
                "camera_id": "cam0",
                "pts_source": "container",
                "extra": {
                    "timeline": {
                        "epochs_opened": 3,
                        "pts_backwards_within_epoch": 2,
                    }
                },
            }
        ]
    )
    assert summary["reconnects_total"] == 2
    assert summary["pts_backwards_total"] == 2


# --------------------------------------------------------------------------
# The statistic that actually governs a gap measurement
# --------------------------------------------------------------------------

def test_a_slow_ramp_barely_affects_any_duration():
    """
    The first real recording read 0.80 s of maximum deviation, which sounds
    alarming, while a twelve-second gap in the same stretch was wrong by 0.097 s.
    The deviation was a linear ramp, and a ramp almost cancels across a short
    window: what a duration inherits is the DIFFERENCE of two deviations, not
    their level. Reporting the level and calling it the gap error — which the
    first version of this metric did — would have condemned a usable recording.
    """
    fidelity = TimelineFidelity()
    fidelity.set_nominal_fps(25.0)

    # Exactly the real clip's first stretch: a true 25 fps file measured
    # against the file's own average rate of 67775/2733.
    average = 67775 / 2733
    for index in range(1, 2474):
        fidelity.observe(index, (index - 1) * 0.04, average)

    result = fidelity.as_dict()
    assert result["max_abs_deviation_s"] == pytest.approx(0.8027, abs=1e-3)
    # ...and yet:
    assert result["interval_error_s"]["<=5s"] < 0.05
    assert result["interval_error_s"]["<=30s"] < 0.25
    assert "usable as-is" not in result["verdict"]


def test_a_stall_moves_the_interval_error_and_the_ramp_does_not():
    """
    Two stalls of 0.44 s each. Any gap that spans one is wrong by that much,
    however small the surrounding deviation is. This is the error that matters
    and the one a maximum-deviation figure hides inside a much larger ramp.
    """
    fidelity = TimelineFidelity()
    fidelity.set_nominal_fps(25.0)

    average = 67775 / 2733
    pts = 0.0
    for index in range(1, 2712):
        fidelity.observe(index, pts, average)
        pts += 0.04
        if index in (2500, 2600):
            pts += 0.44

    result = fidelity.as_dict()
    errors = result["interval_error_s"]
    assert errors["<=1s"] == pytest.approx(0.44, abs=0.02)      # one stall
    assert errors["<=5s"] == pytest.approx(0.85, abs=0.03)      # both
    assert result["long_frame_intervals"] == 2
    assert "0.85 s" in result["verdict"] or "0.84 s" in result["verdict"]


def test_the_verdict_is_taken_from_the_interval_error_not_the_deviation():
    """A big ramp with no steps must not read as unusable."""
    fidelity = TimelineFidelity()
    fidelity.set_nominal_fps(25.0)
    # 0.3% rate mismatch over an hour: deviation ends at ~11 s, but no
    # 30-second interval is wrong by more than ~90 ms.
    for index in range(1, 90_000):
        fidelity.observe(index, (index - 1) * 0.04, 25.0 * 1.003)

    result = fidelity.as_dict()
    assert result["max_abs_deviation_s"] > 10.0
    assert result["interval_error_s"]["<=30s"] < 0.2
    assert "mildly variable" in result["verdict"]


def test_the_series_thins_rather_than_truncating():
    """
    A very long run must not silently stop recording the deviation half way
    through — that would leave the interval error describing only the start.
    """
    fidelity = TimelineFidelity()
    fidelity._series_cap = 100
    fidelity.set_nominal_fps(25.0)
    for index in range(1, 2000):
        fidelity.observe(index, (index - 1) * 0.04, 25.0)

    assert fidelity.as_dict()["series_stride"] > 1
    assert len(fidelity._series) <= 100
    # The last sample must still be near the end of the run, not near the start.
    assert fidelity._series[-1][0] > 70.0


# --------------------------------------------------------------------------
# Decoder threading: the setting that was silently dropped
# --------------------------------------------------------------------------

class _CodecContext:
    """Stands in for PyAV's codec context, which is where the property moved."""

    def __init__(self, accept=True):
        object.__setattr__(self, "accept", accept)
        object.__setattr__(self, "thread_type", None)
        object.__setattr__(self, "thread_count", None)

    def __setattr__(self, name, value):
        if name in ("thread_type", "thread_count") and not self.accept:
            raise AttributeError(f"{name} is not settable on this build")
        object.__setattr__(self, name, value)


class _LockedStream(FakeStream):
    """A stream whose threading properties refuse assignment, like PyAV 18's."""

    def __init__(self, *args, **kwargs):
        object.__setattr__(self, "_locked", False)
        super().__init__(*args, **kwargs)
        object.__setattr__(self, "_locked", True)

    def __setattr__(self, name, value):
        if name in ("thread_type", "thread_count") and getattr(self, "_locked", False):
            raise AttributeError("read-only")
        object.__setattr__(self, name, value)


def test_decoder_threading_is_applied_and_reported():
    """
    The first version assigned `stream.thread_type` inside a bare
    `except Exception: pass`. PyAV moved the property to the codec context, so
    on a current build the assignment raised, nothing was configured, HEVC
    decoded on one thread — and the benchmark reported that as PyAV being 28%
    slower than OpenCV. Silent degradation with confident numbers, which is
    exactly what §9 item 9 is about.
    """
    stream = FakeStream([0, 3600])
    stream.codec_context = _CodecContext()
    av = FakeAv([FakeContainer(stream)])

    source = _source(av)
    source.start()
    threading = source.describe()["decoder_threading"]
    source.stop()

    assert "codec_context" in threading["applied_to"]
    assert stream.codec_context.thread_type == "AUTO"
    assert stream.codec_context.thread_count == 0
    assert "warning" not in threading


def test_a_decoder_that_refuses_threading_says_so_rather_than_passing():
    locked = _LockedStream([0, 3600])
    object.__setattr__(locked, "codec_context", _CodecContext(accept=False))
    av = FakeAv([FakeContainer(locked)])

    source = _source(av)
    source.start()
    threading = source.describe()["decoder_threading"]
    source.stop()

    assert threading["applied_to"] == []
    assert "single-threaded" in threading["warning"]
    assert threading["refused_by"]


def test_an_unknown_thread_type_is_refused():
    from engine.config import IngestConfig

    with pytest.raises(ValueError, match="decoder_thread_type"):
        IngestConfig(decoder_thread_type="MANY")
