"""
PyAV ingest: the same pictures, plus the timeline OpenCV threw away.

ARCHITECTURE.md §5.5. `cv2.VideoCapture.read()` returns a frame and a boolean
and discards the PTS, and without PTS the entire time scheme of §6.6 cannot be
built. PyAV binds libav* directly, so `frame.pts` and `stream.time_base` are
first-class and `pts_seconds = frame.pts * float(stream.time_base)`.

**This file is a binding and nothing else.** Every decision about time lives in
`timeline.py`, which has no idea PyAV exists and is fully unit-tested. What is
left here is: open a container, pick the video stream, pull frames, convert to
BGR, and reconnect when a network stream dies. That split is not tidiness — it
is because the author could not install PyAV in the environment this was
written in, so the surface that only a real decoder can validate had to be
small enough to read and verify by eye. The `av_module` argument exists so the
tests can drive all of it with a fake container; what remains unproven is
whether real PyAV behaves like that fake, which is what
`python -m engine.tools.probe_ingest` is for. Run it before trusting anything
here.

## What this deliberately does not do

**No NVDEC.** §5.5 is explicit: PyAV guarantees PTS, not hardware decode, and
it assumes the PyPI wheel ships an FFmpeg built without CUDA. That assumption
turned out to be **wrong** — PyAV 18.1.0 on Windows carries `hevc_cuvid`,
`h264_cuvid` and the whole QSV family, which `probe_ingest` prints. B9 is
therefore cheaper than the document expects. It is still not free, and this
step still does not take it: asking for a cuvid decoder gets the decode onto
the GPU, but `to_ndarray` copies the frame straight back to host memory, so the
PCIe round trip §5.5 actually cares about survives until the ONNX IO-binding
refactor. Two variables in one step, and the wrong one first.

## Pixels are converted only for frames somebody looks at

`read()` returns a frame whose BGR array is produced on first access of
`frame.image`. The engine decimates to `core.target_fps` by PTS, so at 30 fps in
and 12 fps analysed, more than half of all frames used to be decoded, converted
YUV->BGR at full resolution (6 MB at 1080p), copied, and thrown away. Decode
cannot be skipped (H.264 references); the conversion can. Timeline stamping
still happens for every decoded frame, so PTS checks and fidelity counts are
unchanged.

## Live streams: a reader thread and a one-frame slot (`live_buffer: latest`)

A network source is push: the camera sends at its rate whether or not the
pipeline is ready. When the pipeline thread is also the thread that pulls
packets, every slow inference stalls the socket, MediaMTX's write queue fills,
and it discards packets in the middle of a GOP. The decoder then gets a broken
bitstream: smeared frames, PTS that jumps backwards, boxes that stutter. With
`live_buffer: latest` a dedicated thread drains and decodes at camera rate and
keeps only the newest frame; the pipeline takes whatever is newest when it is
ready. Skipped frames are whole and counted, never corrupt.

**No frame reordering games.** `container.decode()` yields frames in
presentation order, which is what PTS means. If PTS still goes backwards,
`timeline.py` counts it and the bench reports the count.

## Two flags §5.5 calls practically mandatory for production RTSP

`rtsp_transport=tcp`, because UDP loses packets and produces corrupted frames
that will ruin an embedding without ever looking like an error; and an explicit
timeout, so a dead camera does not hang a thread forever.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, Optional, Tuple

from .base import BaseFrameSource
from .timeline import PTS_CONTAINER, StreamTimeline, TimelineFidelity
from ..ports.frame import Frame, FrameMetadata

logger = logging.getLogger(__name__)

NETWORK_SCHEMES = ("rtsp://", "rtsps://", "rtmp://", "http://", "https://", "udp://")
LIVE_BUFFER_MODES = ("none", "latest")


class LazyFrame(Frame):
    """A `Frame` whose pixels are converted on first access of `image`.

    Everything that only needs the timeline (decimation, pacing wrappers, the
    realtime bench proxy) reads `metadata` and never pays for the conversion.
    The decoded `av.VideoFrame` is held until then; it is reference counted by
    libav, so the decoder carrying on in another thread does not touch it.
    """

    def __init__(self, metadata: FrameMetadata, convert: Callable[[], Any]) -> None:
        # Deliberately not calling Frame.__init__: `image` is a property here.
        self.metadata = metadata
        self._convert: Optional[Callable[[], Any]] = convert
        self._image: Any = None

    @property
    def image(self) -> Any:  # type: ignore[override]
        if self._image is None and self._convert is not None:
            self._image = self._convert()
            self._convert = None
        return self._image

    @image.setter
    def image(self, value: Any) -> None:
        self._image = value
        self._convert = None

    @property
    def is_converted(self) -> bool:
        return self._image is not None


class PyAVSource(BaseFrameSource):
    """Frame source with a real timeline. Files and network streams."""

    def __init__(
        self,
        uri: str,
        source_id: str = "pyav",
        rtsp_transport: str = "tcp",
        timeout_seconds: float = 8.0,
        reconnect_attempts: int = 0,
        reconnect_backoff_seconds: float = 1.0,
        max_reconnect_backoff_seconds: float = 30.0,
        measure_timeline_fidelity: bool = True,
        decoder_thread_type: str = "AUTO",
        decoder_threads: int = 0,
        colour_conversion: str = "to_ndarray",
        live_buffer: str = "none",
        av_module: Any = None,
    ) -> None:
        if live_buffer not in LIVE_BUFFER_MODES:
            raise ValueError(
                f"Unknown live_buffer {live_buffer!r}. Expected one of "
                f"{', '.join(LIVE_BUFFER_MODES)}."
            )
        if colour_conversion not in ("to_ndarray", "reformatter"):
            raise ValueError(
                f"Unknown colour_conversion {colour_conversion!r}. Expected "
                f"'to_ndarray' or 'reformatter'."
            )
        super().__init__(source_id=source_id)
        self._uri = str(uri)
        self._rtsp_transport = rtsp_transport
        self._timeout_seconds = float(timeout_seconds)
        self._reconnect_attempts = int(reconnect_attempts)
        self._reconnect_backoff = float(reconnect_backoff_seconds)
        self._max_backoff = float(max_reconnect_backoff_seconds)
        self._thread_type = decoder_thread_type
        self._thread_count = int(decoder_threads)
        self._threading: Dict[str, Any] = {}
        self._colour_conversion = colour_conversion
        self._reformatter: Any = None
        self._av = av_module
        self._live_buffer = live_buffer

        # Reader-thread state (live_buffer == "latest" on a network stream).
        self._reader: Optional[threading.Thread] = None
        self._reader_stop = threading.Event()
        self._slot_lock = threading.Condition()
        self._slot: Optional[Frame] = None
        self._reader_done = False
        self._frames_taken = 0
        self._frames_overwritten = 0
        # Newest decoded position, written by whichever thread decodes. A pair
        # (epoch, pts) assigned in one statement, so a reader never sees the pts
        # of one epoch with the number of another.
        self._latest_decoded: Optional[Tuple[int, float]] = None

        self._container: Any = None
        self._stream: Any = None
        self._frames: Optional[Iterator[Any]] = None
        self._time_base: float = 0.0

        self._fps: float = 0.0
        self._nominal_fps: float = 0.0
        self._width: int = 0
        self._height: int = 0
        self._declared_frames: int = 0
        self._duration_seconds: float = 0.0

        self.timeline = StreamTimeline(source_id=source_id)
        self.fidelity = TimelineFidelity() if measure_timeline_fidelity else None

    # -- lifecycle --------------------------------------------------------

    @property
    def is_network_stream(self) -> bool:
        return self._uri.lower().startswith(NETWORK_SCHEMES)

    @property
    def latest_decoded(self) -> Optional[Tuple[int, float]]:
        """(stream_epoch, pts) of the newest decoded frame, or None.

        With the reader thread this runs ahead of what the pipeline is
        analysing; the difference is the analysis lag (04 §6, P17). Without it,
        both are the same frame and the lag hides in the socket buffer instead.
        """
        return self._latest_decoded

    @property
    def frames_replaced(self) -> int:
        """Frames the reader decoded but replaced before the pipeline took them."""
        return self._frames_overwritten

    @property
    def uses_reader_thread(self) -> bool:
        """Only network streams: a file is a pull source and keeps its pace."""
        return self._live_buffer == "latest" and self.is_network_stream

    def _import_av(self) -> Any:
        if self._av is not None:
            return self._av
        try:
            import av  # noqa: PLC0415 — deliberately lazy; see ingest/__init__.py
        except ImportError as exc:
            raise RuntimeError(
                "PyAV is not installed, so there is no real PTS and every "
                "timestamp downstream would be an assumption "
                "(ARCHITECTURE.md §5.5). Install it with `pip install av`, or "
                "set ingest.backend: opencv and accept a derived timeline."
            ) from exc
        self._av = av
        return av

    def _open_options(self) -> Dict[str, str]:
        if not self.is_network_stream:
            return {}
        micros = str(int(self._timeout_seconds * 1_000_000))
        return {
            # UDP drops packets and hands back corrupted frames that damage an
            # embedding without ever raising (§5.5).
            "rtsp_transport": self._rtsp_transport,
            # Both spellings: ffmpeg renamed `stimeout` to `timeout` for the
            # rtsp demuxer, and which one is honoured depends on the build.
            # An unknown option is ignored, so setting both is safe and setting
            # neither means a dead camera hangs the thread for ever.
            "stimeout": micros,
            "timeout": micros,
            "max_delay": str(int(self._timeout_seconds * 1_000_000)),
        }

    def _open_container(self) -> None:
        av = self._import_av()
        self._container = av.open(self._uri, options=self._open_options())

        try:
            self._stream = self._container.streams.video[0]
        except (IndexError, AttributeError) as exc:
            raise RuntimeError(f"No video stream in {self._uri}") from exc

        # Audio is demuxed away by decoding only this stream. The test clip has
        # an audio track; paying to decode it would be a silent tax.
        self._threading = self._configure_decoder_threads()

        self._time_base = float(getattr(self._stream, "time_base", 0) or 0)
        self._width = int(getattr(self._stream, "width", 0) or 0)
        self._height = int(getattr(self._stream, "height", 0) or 0)
        self._declared_frames = int(getattr(self._stream, "frames", 0) or 0)

        average = _as_float(getattr(self._stream, "average_rate", None))
        guessed = _as_float(getattr(self._stream, "guessed_rate", None))
        self._fps = average or guessed or 0.0
        self._nominal_fps = guessed or average or 0.0

        self._duration_seconds = _stream_duration_seconds(
            self._stream, self._container, self._time_base
        )

        if self.fidelity is not None:
            self.fidelity.set_nominal_fps(self._fps)

        self._frames = self._container.decode(self._stream)
        self.timeline.begin_epoch()

        logger.info(
            "[%s] opened %s: %dx%d, average_rate %.4f, guessed_rate %.4f, "
            "time_base %g, declared frames %s, duration %.2fs%s",
            self._source_id,
            self._uri,
            self._width,
            self._height,
            self._fps,
            self._nominal_fps,
            self._time_base,
            self._declared_frames or "unknown",
            self._duration_seconds,
            (
                "  [variable rate: average_rate != guessed_rate]"
                if self._fps and self._nominal_fps
                and abs(self._fps - self._nominal_fps) > 1e-6
                else ""
            ),
        )

    def _configure_decoder_threads(self) -> Dict[str, Any]:
        """
        Turn on multi-threaded decode, and say so when it does not take.

        This used to be three lines: assign `stream.thread_type = "AUTO"` inside
        a `try` whose `except Exception` did `pass`. PyAV moved that property
        onto the codec context, so on a current PyAV the assignment raised, the
        exception was swallowed, and HEVC decoded on one thread — while OpenCV's
        FFmpeg defaulted to all of them. The first honest timing run put OpenCV
        28% ahead and the tool duly reported it as a property of PyAV.

        It was a property of this function. `except Exception: pass` around a
        performance setting is the same silent degradation ARCHITECTURE.md §9
        item 9 is about, wearing different clothes: nothing failed, the numbers
        were simply wrong and confident. So now every attempt is recorded, the
        result goes into the report, and a decoder that ends up single-threaded
        says so out loud.

        Both targets are tried because which one is live depends on the PyAV
        version, and the settings must land *before* the first decode — the
        codec context is opened lazily, so here is the last moment they count.
        """
        outcome: Dict[str, Any] = {"requested": self._thread_type, "applied_to": []}
        targets = [
            ("codec_context", getattr(self._stream, "codec_context", None)),
            ("stream", self._stream),
        ]

        for name, target in targets:
            if target is None:
                continue
            try:
                target.thread_type = self._thread_type
                # 0 means "one per core". Left unset, some builds use 1.
                try:
                    target.thread_count = self._thread_count
                except Exception:
                    pass
                outcome["applied_to"].append(name)
            except Exception as exc:
                outcome.setdefault("refused_by", {})[name] = repr(exc)

        if not outcome["applied_to"]:
            outcome["warning"] = (
                "decoder threading could not be configured on this PyAV build; "
                "decode is probably single-threaded and any decode-cost number "
                "from this run understates the hardware"
            )
            logger.warning("[%s] %s", self._source_id, outcome["warning"])
        else:
            logger.info(
                "[%s] decoder threading %s applied to %s",
                self._source_id,
                self._thread_type,
                ", ".join(outcome["applied_to"]),
            )
        return outcome

    def start(self) -> None:
        if self._is_running:
            return
        # Opened on the caller's thread so a bad URL still raises where the
        # camera supervisor can report it (camera.failed), threaded or not.
        self._open_container()
        self._frame_count = 0
        self._is_running = True
        if self.uses_reader_thread:
            self._reader_stop.clear()
            with self._slot_lock:
                self._slot = None
                self._reader_done = False
            self._frames_taken = 0
            self._frames_overwritten = 0
            self._reader = threading.Thread(
                target=self._reader_loop,
                name=f"ingest-{self._source_id}",
                daemon=True,
            )
            self._reader.start()

    def stop(self) -> None:
        if not self._is_running:
            return
        self._is_running = False
        if self._reader is not None:
            self._reader_stop.set()
            with self._slot_lock:
                self._slot_lock.notify_all()
            # The reader owns the container while it runs and closes it on its
            # way out. A blocked read returns within the socket timeout.
            self._reader.join(timeout=self._timeout_seconds + 2.0)
            if self._reader.is_alive():
                logger.warning(
                    "[%s] reader thread did not exit within %.0fs; leaving the "
                    "container to it rather than closing it under a live decode.",
                    self._source_id,
                    self._timeout_seconds + 2.0,
                )
            self._reader = None
        else:
            self._close_container()
        if self.uses_reader_thread:
            logger.info(
                "[%s] stopped after %d frames decoded, %d handed to the pipeline, "
                "%d replaced by a newer frame before being taken.",
                self._source_id,
                self._frame_count,
                self._frames_taken,
                self._frames_overwritten,
            )
        else:
            logger.info("[%s] stopped after %d frames.", self._source_id, self._frame_count)

    def _close_container(self) -> None:
        self._frames = None
        if self._container is not None:
            try:
                self._container.close()
            except Exception as exc:  # pragma: no cover
                logger.warning("[%s] error closing container: %s", self._source_id, exc)
            self._container = None

    # -- reading ----------------------------------------------------------

    def read(self) -> Optional[Frame]:
        if not self._is_running:
            return None
        if self._reader is not None:
            return self._take_latest()
        if self._frames is None:
            return None
        return self._decode_next()

    def _decode_next(self) -> Optional[Frame]:
        """Next decoded frame, reconnecting a network stream when it ends."""
        while True:
            if self._frames is None:
                return None
            try:
                av_frame = next(self._frames)
            except StopIteration:
                if self._reconnect():
                    continue
                return None
            except Exception as exc:
                # A decode error on a live stream is a reconnect candidate; on
                # a file it is the end of what can be trusted, and the caller's
                # truncation check (streams/local.py) turns a short read into an
                # error rather than a finished run.
                if self._reader_stop.is_set():
                    return None
                logger.warning("[%s] decode error: %s", self._source_id, exc)
                if self._reconnect():
                    continue
                return None

            return self._to_frame(av_frame)

    # -- reader thread (live_buffer: latest) ------------------------------

    def _reader_loop(self) -> None:
        try:
            while not self._reader_stop.is_set():
                frame = self._decode_next()
                if frame is None:
                    break
                with self._slot_lock:
                    if self._slot is not None:
                        self._frames_overwritten += 1
                    self._slot = frame
                    self._slot_lock.notify()
        except Exception:  # pragma: no cover - reported, then treated as end
            logger.exception("[%s] reader thread failed", self._source_id)
        finally:
            self._close_container()
            with self._slot_lock:
                self._reader_done = True
                self._slot_lock.notify_all()

    def _take_latest(self) -> Optional[Frame]:
        """Newest decoded frame; blocks until one arrives or the stream ends."""
        with self._slot_lock:
            while self._slot is None and not self._reader_done and self._is_running:
                self._slot_lock.wait(timeout=0.5)
            frame = self._slot
            self._slot = None
        if frame is not None:
            self._frames_taken += 1
        return frame

    def _to_frame(self, av_frame: Any) -> Frame:
        self._frame_count += 1

        raw_pts = None
        pts_ticks = getattr(av_frame, "pts", None)
        if pts_ticks is not None and self._time_base:
            raw_pts = float(pts_ticks) * self._time_base
        elif getattr(av_frame, "time", None) is not None:
            raw_pts = float(av_frame.time)

        stamp = self.timeline.stamp(raw_pts)
        if stamp.pts is not None:
            self._latest_decoded = (self.timeline.epoch, float(stamp.pts))

        if self.fidelity is not None and stamp.pts is not None and self._fps > 0:
            # The stream-relative value, which is what `(index - 1) / fps` also
            # measures from. Comparing the container base against a timeline
            # that starts at zero would report the base itself as deviation.
            self.fidelity.observe(self._frame_count, stamp.pts, self._fps)

        if not self._width or not self._height:
            self._width = int(getattr(av_frame, "width", 0) or 0)
            self._height = int(getattr(av_frame, "height", 0) or 0)

        # Pixels on demand: a frame the engine decimates away is never
        # converted (see the module docstring).
        return LazyFrame(
            convert=lambda: self._to_bgr(av_frame),
            metadata=FrameMetadata(
                frame_id=self._frame_count,
                timestamp=time.time(),
                source_id=self._source_id,
                fps=self._fps,
                width=self._width,
                height=self._height,
                pts=stamp.pts,
                pts_source=PTS_CONTAINER if stamp.pts is not None else "none",
                stream_epoch=self.timeline.epoch,
                wallclock=stamp.wallclock,
                container_pts=stamp.container_pts,
                pts_wallclock_offset=stamp.offset,
            ),
        )

    def _to_bgr(self, av_frame: Any):
        """
        The decoded frame as a BGR ndarray — by one of two routes, on purpose.

        `probe_ingest` measured PyAV at 80 fps against OpenCV's 113 on the same
        1080p HEVC file, with decoder threading verified as applied to both the
        codec context and the stream. A 29% gap outside a 3.3% run-to-run spread
        is not noise, and "PyAV is slower" is not a finding — it is where the
        investigation starts. The remaining per-frame work after decode is the
        colour conversion, and `to_ndarray(format=...)` builds its conversion
        context and its destination buffer on every single call.

        So there are two paths and the probe times both, because §16 says a
        step is measured rather than argued about, and because I am not going to
        assert a speedup I cannot reproduce on this machine:

        `to_ndarray` — what B4 shipped. Unchanged, and still the default, so
        nothing about the committed baseline moves under anyone's feet.

        `reformatter` — one `VideoReformatter` reused for the lifetime of the
        source, converting into its own cached context. Same pixels; the
        difference is how many times libswscale is asked to set itself up.

        If the second wins on the real recording, it becomes the default in its
        own commit with the delta recorded. If it does not, `to_ndarray` was
        never the problem and the next suspect is frame threading depth.
        """
        if self._colour_conversion == "to_ndarray":
            return av_frame.to_ndarray(format="bgr24")

        if self._reformatter is None:
            av = self._import_av()
            self._reformatter = av.video.reformatter.VideoReformatter()
        converted = self._reformatter.reformat(av_frame, format="bgr24")
        return converted.to_ndarray()

    def _reconnect(self) -> bool:
        """
        Re-opens a network stream, bumping the epoch. False means give up.

        A file never reconnects: end of file is end of file, and retrying would
        turn a truncated recording into an endless loop that looks like
        progress.
        """
        if not self.is_network_stream or self._reconnect_attempts <= 0:
            return False

        backoff = self._reconnect_backoff
        for attempt in range(1, self._reconnect_attempts + 1):
            logger.warning(
                "[%s] stream ended; reconnect attempt %d/%d in %.1fs",
                self._source_id,
                attempt,
                self._reconnect_attempts,
                backoff,
            )
            if self._reader_stop.wait(backoff):
                return False
            self._close_container()
            try:
                self._open_container()
            except Exception as exc:
                logger.warning("[%s] reconnect failed: %s", self._source_id, exc)
                backoff = min(backoff * 2.0, self._max_backoff)
                continue
            return True

        logger.error(
            "[%s] giving up after %d reconnect attempts.",
            self._source_id,
            self._reconnect_attempts,
        )
        return False

    # -- description ------------------------------------------------------

    @property
    def fps(self) -> float:
        return self._fps

    @property
    def nominal_fps(self) -> float:
        """`guessed_rate` — the rate the container claims, before frames go missing."""
        return self._nominal_fps

    @property
    def resolution(self) -> Tuple[int, int]:
        return (self._width, self._height)

    @property
    def total_frames(self) -> int:
        """
        How many frames the source should produce, or 0 if unknowable.

        `stream.frames` is 0 for many containers and for every live stream, and
        the truncated-run check in streams/local.py depends on this number. So
        when the container does not count frames but does know its duration, the
        count is derived from duration × average_rate. That is an estimate, and
        it is used only to detect a run that stopped at a fraction of the
        source — a job an estimate does fine and silence does not.
        """
        if self._declared_frames:
            return self._declared_frames
        if self._duration_seconds > 0 and self._fps > 0:
            return int(round(self._duration_seconds * self._fps))
        return 0

    @property
    def duration_seconds(self) -> float:
        return self._duration_seconds

    def describe(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "backend": "pyav",
            "uri": self._uri,
            "is_network_stream": self.is_network_stream,
            "average_rate": self._fps,
            "guessed_rate": self._nominal_fps,
            "time_base": self._time_base,
            "declared_frames": self._declared_frames,
            "duration_seconds": round(self._duration_seconds, 4),
            "decoder_threading": self._threading,
            "colour_conversion": self._colour_conversion,
            "live_buffer": self._live_buffer,
            "timeline": self.timeline.as_dict(),
        }
        if self.uses_reader_thread:
            out["live_reader"] = {
                "frames_decoded": self._frame_count,
                "frames_taken": self._frames_taken,
                "frames_replaced_before_taken": self._frames_overwritten,
            }
        if self.fidelity is not None:
            out["timeline_fidelity"] = self.fidelity.as_dict()
        return out


def _as_float(value: Any) -> float:
    """Fractions, ints, None — all become a float or 0.0."""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _stream_duration_seconds(stream: Any, container: Any, time_base: float) -> float:
    duration = getattr(stream, "duration", None)
    if duration and time_base:
        return float(duration) * time_base
    container_duration = getattr(container, "duration", None)
    if container_duration:
        # container.duration is in AV_TIME_BASE units (microseconds).
        return float(container_duration) / 1_000_000.0
    return 0.0


def probe_codecs(av_module: Any = None) -> Dict[str, Any]:
    """
    Whether this PyAV build can reach NVDEC at all. §5.5 says not to trust the
    documentation and to check — this is that check, in one call, and on the
    first machine it ran on it contradicted the document.
    """
    av = av_module
    if av is None:
        try:
            import av  # noqa: PLC0415
        except ImportError:
            return {"available": False, "hardware_decoders": [], "reason": "PyAV not installed"}
    codecs = sorted(getattr(av, "codecs_available", []) or [])
    hardware = [c for c in codecs if "cuvid" in c or "nvdec" in c or "qsv" in c]
    return {
        "available": True,
        "pyav_version": getattr(av, "__version__", "unknown"),
        "hardware_decoders": hardware,
        "note": (
            (
                "this build DOES carry hardware decoders, which contradicts the "
                "assumption in §5.5 that a PyPI wheel would not. That makes B9 "
                "cheaper than planned but not free: asking for a cuvid decoder "
                "still ends with to_ndarray copying the frame back to host "
                "memory, so the PCIe round trip §5.5 actually cares about "
                "survives until the ONNX IO-binding refactor. Nothing to do "
                "here; B4 is about PTS."
            )
            if hardware
            else (
                "no hardware decoders in this build, which is what §5.5 "
                "expects from a PyPI wheel. That is fine — B4 is about PTS, "
                "and NVDEC is a separate, later, profile-driven decision."
            )
        ),
    }
