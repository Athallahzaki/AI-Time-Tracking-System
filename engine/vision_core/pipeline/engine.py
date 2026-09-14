from __future__ import annotations

import logging
import signal
import time
from typing import Any, Callable, List, Optional, Tuple

from ..contracts.detection import Detection
from ..contracts.frame import Frame
from ..contracts.interfaces import (
    FrameSink,
    FrameSource,
    ObjectDetector,
    ObjectTracker,
    TrackListener,
)
from ..contracts.tracking import Track, TrackState
from ..metrics.performance import PerformanceMetrics
from .config import VisionCoreConfig
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
        config: Optional[VisionCoreConfig] = None,
    ) -> None:
        self._source = source
        self._detector = detector
        self._tracker = tracker
        self._config = config or VisionCoreConfig()

        self._listeners: List[TrackListener] = []
        self._sinks: List[FrameSink] = []
        self._event_handlers: List[Callable[[Any], None]] = []

        self._metrics = PerformanceMetrics()
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

        t_ingest = (time.perf_counter() - t0) * 1000.0
        self._metrics.record_latency(
            "source_ingest",
            t_ingest,
        )

        self._frame_count += 1

        # 2. Detection cadence
        if (
            self._frame_count % self._config.detection_interval == 0
            or not self._cached_detections
        ):
            t0 = time.perf_counter()

            detections = self._detector.detect(frame)

            t_det = (time.perf_counter() - t0) * 1000.0
            self._metrics.record_latency(
                "detector",
                t_det,
            )

            self._cached_detections = detections
        else:
            detections = self._cached_detections

        # 3. Tracker
        t0 = time.perf_counter()

        tracks = self._tracker.update(
            detections,
            frame,
        )

        t_track = (time.perf_counter() - t0) * 1000.0
        self._metrics.record_latency(
            "tracker",
            t_track,
        )

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

        t_listeners = (
            time.perf_counter() - t0
        ) * 1000.0

        self._metrics.record_latency(
            "listeners",
            t_listeners,
        )

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

        t_sinks = (
            time.perf_counter() - t0
        ) * 1000.0

        self._metrics.record_latency(
            "sinks",
            t_sinks,
        )

        # Metrics
        self._metrics.record_frame()

        t_total = (
            time.perf_counter() - t_start
        ) * 1000.0

        self._metrics.record_latency(
            "total_pipeline",
            t_total,
        )

        return frame, tracks

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
                total_frames=self._metrics.total_frames,
                uptime_seconds=self._metrics.uptime_seconds,
            )
        )

        logger.info(
            "VisionEngine stopped. Final metrics: "
            f"{self._metrics.summary_str()}"
        )

    @property
    def metrics(self) -> PerformanceMetrics:
        return self._metrics

    @property
    def is_running(self) -> bool:
        return self._is_running