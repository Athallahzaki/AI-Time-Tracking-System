from __future__ import annotations

import logging
import signal
import time
from typing import Any, Callable, List, Optional, Tuple
from ..ports.result import EngineResult, TrackResult
from ..ports.detection import Detection
from ..ports.frame import Frame
from ..ports.interfaces import (
    FrameSink,
    FrameSource,
    ObjectDetector,
    ObjectTracker,
    TrackListener,
)
from ..ports.tracking import Track, TrackState
from .instrument import NullRecorder, Recorder
from ..config import EngineConfig
from .events import (
    EngineStartedEvent,
    EngineStoppedEvent,
    TrackCreatedEvent,
    TrackLostEvent,
    TrackRemovedEvent,
    TrackUpdatedEvent,
)

logger = logging.getLogger(__name__)


class VisionEngine:
    """
    Modular orchestrator for video ingestion, object detection, and tracking.

    Completely decoupled from domain plugins such as face recognition.
    """

    def __init__(
        self,
        source: FrameSource,
        detector: ObjectDetector,
        tracker: ObjectTracker,
        config: Optional[EngineConfig] = None,
        recorder: Optional[Recorder] = None,
    ) -> None:
        self._source = source
        self._detector = detector
        self._tracker = tracker
        self._config = config or EngineConfig()

        self._listeners: List[TrackListener] = []
        self._sinks: List[FrameSink] = []
        self._event_handlers: List[Callable[[Any], None]] = []

        self._metrics: Recorder = recorder or NullRecorder()
        self._is_running = False
        self._frame_count = 0
        self._cached_detections: List[Detection] = []

        # Known tracks are retained until the tracker stops returning them.
        # This lets us distinguish LOST from actual removal.
        self._known_tracks: dict[int, Track] = {}

    def add_listener(self, listener: TrackListener) -> VisionEngine:
        """Subscribes a track listener."""
        if listener not in self._listeners:
            self._listeners.append(listener)
        return self

    def remove_listener(self, listener: TrackListener) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def add_sink(self, sink: FrameSink) -> VisionEngine:
        """Subscribes an output sink."""
        if sink not in self._sinks:
            self._sinks.append(sink)
        return self

    def add_event_handler(
        self,
        handler: Callable[[Any], None],
    ) -> VisionEngine:
        """Subscribes an event callback."""
        if handler not in self._event_handlers:
            self._event_handlers.append(handler)
        return self

    def _emit_event(self, event: Any) -> None:
        for handler in self._event_handlers:
            try:
                handler(event)
            except Exception as exc:
                logger.error(
                    f"Error in event handler: {exc}",
                    exc_info=True,
                )

    def start(self) -> None:
        """Starts the vision engine and frame source."""
        if self._is_running:
            return

        logger.info("Starting VisionEngine...")

        if self._config.auto_warmup:
            logger.info("Warming up detector...")
            self._detector.warmup()

        self._source.start()
        self._is_running = True
        self._frame_count = 0

        self._emit_event(
            EngineStartedEvent(
                source_id=self._config.source_uri,
            )
        )

        logger.info("VisionEngine started successfully.")

    def step(self) -> Tuple[Optional[Frame], List[Track]]:
        """
        Executes one complete pipeline step:

        Frame ingestion
            -> detection
            -> tracking
            -> lifecycle events
            -> listeners
            -> sinks
        """
        if not self._is_running:
            return None, []

        t_start = time.perf_counter()

        # 1. Fetch frame
        t0 = time.perf_counter()

        frame = self._source.read()

        if frame is None:
            return None, []

        t_ingest_end = time.perf_counter()

        # Name the frame before recording anything against it. Without this the
        # spans below are durations with no camera and no timeline position —
        # see pipeline/instrument.py for why that distinction is load-bearing.
        self._metrics.begin_frame(
            camera_id=frame.metadata.source_id,
            frame_id=frame.frame_id,
            pts=self._frame_pts(frame),
        )
        self._metrics.record_span("source_ingest", t0, t_ingest_end)

        self._frame_count += 1

        # 2. Detection cadence
        if (
            self._frame_count % self._config.detection_interval == 0
            or not self._cached_detections
        ):
            t0 = time.perf_counter()

            detections = self._detector.detect(frame)

            self._metrics.record_span("detector", t0, time.perf_counter())

            self._cached_detections = detections
        else:
            detections = self._cached_detections

        # 3. Tracker
        t0 = time.perf_counter()

        tracks = self._tracker.update(
            detections,
            frame,
        )

        self._metrics.record_span("tracker", t0, time.perf_counter())

        # 4. Track lifecycle
        current_track_ids = {
            track.track_id
            for track in tracks
        }

        for track in tracks:
            previous = self._known_tracks.get(
                track.track_id
            )

            # New track
            if (
                previous is None
                and track.state
                in (
                    TrackState.NEW,
                    TrackState.TRACKED,
                )
            ):
                self._emit_event(
                    TrackCreatedEvent(
                        track=track,
                    )
                )

            # Transition into LOST.
            # Only emit once, not once per LOST frame.
            if (
                track.state == TrackState.LOST
                and (
                    previous is None
                    or previous.state != TrackState.LOST
                )
            ):
                self._emit_event(
                    TrackLostEvent(
                        track=track,
                    )
                )

                for listener in self._listeners:
                    try:
                        listener.on_track_lost(track)
                    except Exception as exc:
                        logger.error(
                            f"Error in track-lost listener "
                            f"{listener}: {exc}",
                            exc_info=True,
                        )

            # Active track update
            if track.state in (
                TrackState.NEW,
                TrackState.TRACKED,
            ):
                self._emit_event(
                    TrackUpdatedEvent(
                        track=track,
                    )
                )

            # Keep the latest state so we can detect transitions.
            self._known_tracks[track.track_id] = track

        # A track that disappears completely from tracker output
        # is now considered REMOVED.
        removed_track_ids = (
            set(self._known_tracks)
            - current_track_ids
        )

        for track_id in removed_track_ids:
            removed_track = self._known_tracks.pop(track_id)

            self._emit_event(
                TrackRemovedEvent(
                    track_id=track_id,
                    dwell_time=removed_track.dwell_time,
                )
            )

            for listener in self._listeners:
                try:
                    listener.on_track_removed(
                        removed_track,
                    )
                except Exception as exc:
                    logger.error(
                        f"Error in track-removed listener "
                        f"{listener}: {exc}",
                        exc_info=True,
                    )

        # 5. Domain listeners
        t0 = time.perf_counter()

        for listener in self._listeners:
            try:
                listener.on_tracks_updated(
                    tracks,
                    frame,
                )
            except Exception as exc:
                logger.error(
                    f"Error in listener {listener}: {exc}",
                    exc_info=True,
                )

        self._metrics.record_span("listeners", t0, time.perf_counter())

        # 6. Sinks
        t0 = time.perf_counter()

        for sink in self._sinks:
            try:
                sink.write(
                    frame,
                    tracks,
                )
            except Exception as exc:
                logger.error(
                    f"Error in sink {sink}: {exc}",
                    exc_info=True,
                )

        self._metrics.record_span("sinks", t0, time.perf_counter())

        self._metrics.record_span("total_pipeline", t_start, time.perf_counter())
        self._metrics.record_frame()

        return frame, tracks

    @staticmethod
    def _frame_pts(frame: Frame) -> float:
        """
        The frame's position on the source timeline, in seconds.

        Since B4 this is a typed field the source fills in, and the source also
        says where the number came from (`pts_source`). The engine does not care
        which: it passes the timeline through and lets the report and the bench
        decide how far to trust it.
        """
        pts = frame.metadata.pts
        return 0.0 if pts is None else float(pts)

    def run(self) -> None:
        """Runs the main processing loop."""
        self.start()

        def _signal_handler(sig, frame):
            logger.info(
                f"Received shutdown signal ({sig}). "
                f"Stopping VisionEngine..."
            )
            self.stop()

        try:
            signal.signal(
                signal.SIGINT,
                _signal_handler,
            )
            signal.signal(
                signal.SIGTERM,
                _signal_handler,
            )
        except (ValueError, AttributeError):
            pass

        logger.info(
            "VisionEngine entering processing loop..."
        )

        try:
            while self._is_running:
                frame, _tracks = self.step()

                if (
                    frame is None
                    and not self._source.is_running
                ):
                    logger.info(
                        "Source stopped or reached end of stream."
                    )
                    break

        except KeyboardInterrupt:
            logger.info("Interrupted by user.")

        finally:
            self.stop()

    def stop(self) -> None:
        """Gracefully stops sinks and source."""
        if not self._is_running:
            return

        self._is_running = False

        logger.info(
            "Stopping VisionEngine components..."
        )

        self._source.stop()

        for sink in self._sinks:
            try:
                sink.close()
            except Exception as exc:
                logger.warning(
                    f"Error closing sink: {exc}"
                )

        self._emit_event(
            EngineStoppedEvent(
                total_frames=getattr(self._metrics, "total_frames", 0),
                uptime_seconds=0.0,
            )
        )

        logger.info(
            "VisionEngine stopped. "
            f"{getattr(self._metrics, 'summary_str', lambda: '')()}"
        )

    @property
    def metrics(self) -> Recorder:
        return self._metrics

    @property
    def is_running(self) -> bool:
        return self._is_running

    def process_frame(self) -> EngineResult | None:
        """
        Processes one frame and returns the backend-facing public result.

        The existing step() API remains unchanged for internal/runtime use.
        """
        frame, tracks = self.step()

        if frame is None:
            return None

        results = [
            TrackResult(
                track_id=track.track_id,
                bbox=track.bbox,
                identity_id=track.attributes.get("identity"),
                recognition_status=track.attributes.get(
                    "recognition_status"
                ),
                similarity=float(
                    track.attributes.get(
                        "similarity",
                        0.0,
                    )
                ),
            )
            for track in tracks
        ]

        return EngineResult(
            frame_id=frame.frame_id,
            timestamp=frame.timestamp,
            tracks=results,
        )