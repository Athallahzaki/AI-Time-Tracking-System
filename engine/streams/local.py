"""
In-process adapter: runs the pipeline and yields `FrameObservation`s.

This is the only file allowed to know both that `VisionEngine` exists and that
`TrackStream` exists. Everything downstream — the benchmark above all — sees
only the port. See ports/observation.py for why.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Iterator, Optional

from .. import factory
from ..config import EngineConfig
from ..factory import SourceWrapper
from ..pipeline.instrument import Recorder
from ..ports.geometry import NormalizedBox
from ..ports.observation import (
    FrameObservation,
    StreamDescriptor,
    TrackObservation,
)

logger = logging.getLogger("engine.streams.local")


class TruncatedSourceError(RuntimeError):
    """The source stopped before it ran out of frames."""


class LocalTrackStream:
    """Satisfies `ports.observation.TrackStream` by running the pipeline here."""

    def __init__(
        self,
        config: EngineConfig,
        camera_id: str = "cam0",
        max_frames: Optional[int] = None,
        recorder: Optional[Recorder] = None,
        wrap_source: Optional[SourceWrapper] = None,
    ) -> None:
        self._config = config
        self._camera_id = camera_id
        self._max_frames = max_frames
        self._recorder = recorder
        self._wrap_source = wrap_source

        self._engine: Any = None
        self._source: Any = None
        self._descriptor: Optional[StreamDescriptor] = None
        self._frames_read = 0
        self._closed = False

    # -- TrackStream ------------------------------------------------------

    def open(self) -> StreamDescriptor:
        engine, source, source_fps = factory.build_engine(
            self._config,
            max_frames=self._max_frames,
            recorder=self._recorder,
            source_id=self._camera_id,
            wrap_source=self._wrap_source,
        )
        self._engine = engine
        self._source = source
        engine.start()

        width, height = getattr(source, "resolution", (0, 0))
        self._descriptor = StreamDescriptor(
            camera_id=self._camera_id,
            # What actually ran, not what the config named. A fallback that
            # reports the requested class is the failure mode strict_mode is
            # there to stop; this is the same rule applied to the report.
            source_class=type(source).__name__,
            detector_class=type(engine._detector).__name__,
            tracker_class=type(engine._tracker).__name__,
            source_fps=source_fps,
            effective_fps=self._config.effective_fps(source_fps),
            width=int(width or 0),
            height=int(height or 0),
            total_frames=int(getattr(source, "total_frames", 0) or 0) or None,
            # Where the timeline came from. Provisional until the first frame
            # says otherwise — the source knows, and it is asked below rather
            # than assumed here.
            pts_source="unknown",
            extra=(
                source.describe() if hasattr(source, "describe") else {}
            ),
        )
        return self._descriptor

    def observations(self) -> Iterator[FrameObservation]:
        if self._engine is None or self._descriptor is None:
            raise RuntimeError("open() must be called before observations().")

        width = self._descriptor.width
        height = self._descriptor.height
        fps = self._descriptor.source_fps

        while True:
            if self._max_frames is not None and self._frames_read >= self._max_frames:
                break

            frame, tracks = self._engine.step()
            if frame is None:
                break

            self._frames_read += 1

            # A source can report 0x0 before the first frame arrives (mock
            # sources do). Learn the real size from the frame itself rather than
            # normalising against zero.
            if width <= 0 or height <= 0:
                width, height = frame.width, frame.height
                self._descriptor = _with_size(self._descriptor, width, height)

            if self._descriptor.pts_source == "unknown":
                self._descriptor = _with_pts_source(
                    self._descriptor, frame.metadata.pts_source
                )

            yield FrameObservation(
                camera_id=self._camera_id,
                frame_id=frame.frame_id,
                pts=_pts_of(frame, fps),
                wallclock=frame.metadata.wallclock or frame.timestamp,
                width=width,
                height=height,
                pts_source=frame.metadata.pts_source,
                stream_epoch=frame.metadata.stream_epoch,
                tracks=tuple(
                    TrackObservation(
                        track_id=int(track.track_id),
                        box=NormalizedBox.from_pixels(track.bbox, width, height),
                        state=str(getattr(track.state, "value", track.state)),
                        confidence=float(track.confidence),
                    )
                    for track in tracks
                ),
            )

        self._assert_source_was_exhausted()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._engine is not None:
            self._engine.stop()
        # describe() is only complete once the source has run: timeline
        # fidelity and the reconnect count are accumulated, not declared.
        if self._descriptor is not None and hasattr(self._source, "describe"):
            import dataclasses

            self._descriptor = dataclasses.replace(
                self._descriptor, extra=self._source.describe()
            )

    @property
    def descriptor(self) -> Optional[StreamDescriptor]:
        return self._descriptor

    # -- internals --------------------------------------------------------

    @property
    def frames_read(self) -> int:
        return self._frames_read

    def _assert_source_was_exhausted(self) -> None:
        """
        A source that stopped early must not be mistaken for one that finished.

        cv2.VideoCapture.read() returns None both at end-of-stream and on a
        decode failure, and the old code logged both as "Reached end of video".
        A benchmark computed over 6% of a file and reported as a full run is
        exactly the kind of flattering lie strict_mode exists to stop.
        """
        if self._max_frames is not None:
            return
        expected = int(getattr(self._source, "total_frames", 0) or 0)
        if not expected or self._frames_read >= expected:
            return

        # Tolerance, because since B4 `total_frames` may be an estimate:
        # many containers do not count frames, so PyAVSource derives the count
        # from duration x average_rate and can be a frame or two out. The thing
        # this check exists to catch is a run that covered 6% of a file; half a
        # percent of slack does not weaken that, and without it every estimated
        # count would raise on a perfectly complete run.
        shortfall = expected - self._frames_read
        if shortfall <= max(2, int(expected * 0.005)):
            logger.info(
                "[%s] read %d of an expected %d frames; within the tolerance "
                "for an estimated frame count.",
                self._camera_id,
                self._frames_read,
                expected,
            )
            return

        message = (
            f"[{self._camera_id}] source ended after {self._frames_read} of "
            f"{expected} frames ({self._frames_read / expected:.1%}). This is a "
            f"decode failure or a truncated file, not a finished run — any "
            f"number derived from it describes a fraction of the source."
        )
        if self._config.strict_mode:
            raise TruncatedSourceError(message)
        logger.warning("%s (strict_mode is OFF)", message)


def _pts_of(frame: Any, fps: float) -> float:
    pts = frame.metadata.pts
    if pts is not None:
        return float(pts)
    if fps <= 0.0:
        return 0.0
    return (frame.frame_id - 1) / fps


def _with_pts_source(descriptor: StreamDescriptor, pts_source: str) -> StreamDescriptor:
    import dataclasses

    return dataclasses.replace(descriptor, pts_source=pts_source)


def _with_size(descriptor: StreamDescriptor, width: int, height: int) -> StreamDescriptor:
    import dataclasses

    return dataclasses.replace(descriptor, width=width, height=height)
