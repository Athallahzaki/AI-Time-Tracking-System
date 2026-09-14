from __future__ import annotations

import logging
import signal
import sys
import time
from typing import Callable, List, Optional, Tuple

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
    Modular orchestrator for video ingestion, object detection, and multi-object tracking.
    Completely decoupled from domain plugins (such as face recognition) and UI layers.
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
        self._known_track_ids: set[int] = set()

    def add_listener(self, listener: TrackListener) -> VisionEngine:
        """Subscribes a track listener (e.g. face recognizer plugin, analytics, zone monitor)."""
        if listener not in self._listeners:
            self._listeners.append(listener)
        return self

    def remove_listener(self, listener: TrackListener) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def add_sink(self, sink: FrameSink) -> VisionEngine:
        """Subscribes an output visualizer, stream publisher, or video recorder."""
        if sink not in self._sinks:
            self._sinks.append(sink)
        return self

    def add_event_handler(self, handler: Callable[[Any], None]) -> VisionEngine:
        """Subscribes an event callback for lifecycle events."""
        if handler not in self._event_handlers:
            self._event_handlers.append(handler)
        return self

    def _emit_event(self, event: Any) -> None:
        for handler in self._event_handlers:
            try:
                handler(event)
            except Exception as e:
                logger.error(f"Error in event handler: {e}")

    def start(self) -> None:
        """Starts the vision engine and underlying frame source."""
        if self._is_running:
            return

        logger.info("Starting VisionEngine...")
        if self._config.auto_warmup:
            logger.info("Warming up detector...")
            self._detector.warmup()

        self._source.start()
        self._is_running = True
        self._frame_count = 0
        self._emit_event(EngineStartedEvent(source_id=self._config.source_uri))
        logger.info("VisionEngine started successfully.")

    def step(self) -> Tuple[Optional[Frame], List[Track]]:
        """
        Executes a single end-to-end iteration:
        Frame Ingestion -> Object Detection (with interval cadence) -> Multi-Object Tracking -> Listeners & Sinks.
        Returns the processed Frame and active Tracks.
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
        self._metrics.record_latency("source_ingest", t_ingest)

        self._frame_count += 1

        # 2. Run Object Detection (cadenced by detection_interval)
        if (self._frame_count % self._config.detection_interval) == 0 or not self._cached_detections:
            t0 = time.perf_counter()
            detections = self._detector.detect(frame)
            t_det = (time.perf_counter() - t0) * 1000.0
            self._metrics.record_latency("detector", t_det)
            self._cached_detections = detections
        else:
            detections = self._cached_detections

        # 3. Update Multi-Object Tracker
        t0 = time.perf_counter()
        tracks = self._tracker.update(detections, frame)
        t_track = (time.perf_counter() - t0) * 1000.0
        self._metrics.record_latency("tracker", t_track)

        # 4. Process Track Lifecycle Events
        current_tids = {t.track_id for t in tracks if t.state in (TrackState.NEW, TrackState.TRACKED)}
        for t in tracks:
            if t.track_id not in self._known_track_ids and t.state in (TrackState.NEW, TrackState.TRACKED):
                self._known_track_ids.add(t.track_id)
                self._emit_event(TrackCreatedEvent(track=t))
            elif t.state == TrackState.LOST:
                self._emit_event(TrackLostEvent(track=t))

        # Check for removed tracks
        removed_tids = self._known_track_ids - current_tids
        for tid in list(removed_tids):
            # Check if any track with this id is marked REMOVED
            matching_removed = [tr for tr in tracks if tr.track_id == tid and tr.state == TrackState.REMOVED]
            dwell = matching_removed[0].dwell_time if matching_removed else 0.0
            self._known_track_ids.remove(tid)
            self._emit_event(TrackRemovedEvent(track_id=tid, dwell_time=dwell))
            for listener in self._listeners:
                if matching_removed:
                    listener.on_track_lost(matching_removed[0])

        # 5. Notify Listeners (Domain plugins)
        t0 = time.perf_counter()
        for listener in self._listeners:
            try:
                listener.on_tracks_updated(tracks, frame)
            except Exception as e:
                logger.error(f"Error in listener {listener}: {e}", exc_info=True)
        t_listeners = (time.perf_counter() - t0) * 1000.0
        self._metrics.record_latency("listeners", t_listeners)

        # 6. Notify Sinks (Visualizers / Recorders)
        t0 = time.perf_counter()
        for sink in self._sinks:
            try:
                sink.write(frame, tracks)
            except Exception as e:
                logger.error(f"Error in sink {sink}: {e}", exc_info=True)
        t_sinks = (time.perf_counter() - t0) * 1000.0
        self._metrics.record_latency("sinks", t_sinks)

        # Record metrics
        self._metrics.record_frame()
        t_total = (time.perf_counter() - t_start) * 1000.0
        self._metrics.record_latency("total_pipeline", t_total)

        return frame, tracks

    def run(self) -> None:
        """Main execution loop. Runs until stopped or stream ends."""
        self.start()

        def _signal_handler(sig, frame):
            logger.info(f"Received shutdown signal ({sig}). Stopping VisionEngine...")
            self.stop()

        # Register signal handlers if running in main thread
        try:
            signal.signal(signal.SIGINT, _signal_handler)
            signal.signal(signal.SIGTERM, _signal_handler)
        except (ValueError, AttributeError):
            pass

        logger.info("VisionEngine entering processing loop...")
        try:
            while self._is_running:
                frame, tracks = self.step()
                if frame is None and not self._source.is_running:
                    logger.info("Source stopped or reached end of stream.")
                    break
        except KeyboardInterrupt:
            logger.info("Interrupted by user.")
        finally:
            self.stop()

    def stop(self) -> None:
        """Gracefully stops engine, sinks, and sources."""
        if not self._is_running:
            return

        self._is_running = False
        logger.info("Stopping VisionEngine components...")
        self._source.stop()

        for sink in self._sinks:
            try:
                sink.close()
            except Exception as e:
                logger.warning(f"Error closing sink: {e}")

        self._emit_event(
            EngineStoppedEvent(
                total_frames=self._metrics.total_frames,
                uptime_seconds=self._metrics.uptime_seconds,
            )
        )
        logger.info(f"VisionEngine stopped. Final metrics: {self._metrics.summary_str()}")

    @property
    def metrics(self) -> PerformanceMetrics:
        return self._metrics

    @property
    def is_running(self) -> bool:
        return self._is_running
