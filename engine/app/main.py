from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Any, Optional

from ..vision_core import (
    ByteTrackTracker,
    IoUTracker,
    MockDetector,
    MockFrameSource,
    MockTracker,
    OpenCVStreamSource,
    VideoFileSource,
    VisionCoreConfig,
    VisionEngine,
    YOLODetector,
)
from ..plugins.face_recognizer import (
    FaceRecognizerConfig,
    FaceRecognizerPlugin,
    FaceRecognizedEvent,
    PersonUnknownEvent,
    IdentityChangedEvent,
    PluginEvent,
)
from .attendance_tracker import (
    AttendanceConfig,
    AttendanceTracker,
    PersonConfirmedEvent,
    PersonDepartedEvent,
    PersonEnteredEvent,
    SessionLimitReachedEvent,
    SessionWarningEvent,
)
from .config import AppConfig
from .visualizer import OpenCVVisualizer

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s]: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("AI-Vision-Engine")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Production Real-Time AI Vision Engine (Tracking + Face Recognition)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="engine/configs/default_config.yaml",
        help="Path to YAML configuration file.",
    )
    parser.add_argument(
        "--source",
        type=str,
        default=None,
        help="Override video stream source (camera index e.g. 0, RTSP URI, or video path).",
    )
    parser.add_argument(
        "--device",
        type=str,
        default=None,
        help="Override compute device for inference (auto, 0, cuda, cpu).",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Run completely with synthetic mock components for testing/benchmarks without physical cameras or models.",
    )
    parser.add_argument(
        "--no-face-recognition",
        action="store_true",
        help="Disable face recognition plugin completely to run pure detection + tracking core.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run in headless server mode (no GUI window).",
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        default=None,
        help="Maximum frames to process before exiting (useful for automated benchmarks).",
    )
    return parser.parse_args()


def build_app(args: argparse.Namespace) -> VisionEngine:
    """Dependency Injection and Composition of Core, Plugin, and Application layers."""
    # 1. Load configuration
    config_path = Path(args.config)
    if config_path.exists():
        logger.info(f"Loading configuration from {config_path}")
        app_config = AppConfig.from_yaml(config_path)
    else:
        logger.info(f"Configuration file {config_path} not found; using defaults.")
        app_config = AppConfig()

    # CLI Overrides
    if args.source is not None:
        app_config.core.source_uri = args.source
    if args.device is not None:
        app_config.core.device = args.device
    if args.headless:
        app_config.visualizer.enabled = False

    # 2. Assemble FrameSource
    source_uri = app_config.core.source_uri
    if args.mock:
        logger.info("Using MockFrameSource (synthetic stream)...")
        source = MockFrameSource(max_frames=args.max_frames)
    elif source_uri.isdigit():
        source = OpenCVStreamSource(uri=int(source_uri), source_id=f"camera_{source_uri}")
    elif source_uri.startswith("rtsp://") or source_uri.startswith("http://"):
        source = OpenCVStreamSource(uri=source_uri, source_id="rtsp_stream")
    elif Path(source_uri).is_file():
        source = VideoFileSource(filepath=source_uri, source_id="video_file")
    else:
        logger.warning(f"Unknown source URI '{source_uri}', defaulting to OpenCVStreamSource(0)")
        source = OpenCVStreamSource(uri=0, source_id="default_cam")

    # 3. Assemble Detector
    if args.mock:
        detector = MockDetector()
    else:
        detector = YOLODetector(
            model_path=app_config.core.model_path,
            confidence_threshold=0.40,
            image_size=640,
            device=app_config.core.device,
        )

    # 4. Assemble Tracker
    if args.mock:
        tracker = MockTracker()
    else:
        tracker = ByteTrackTracker()

    # 5. Build Core VisionEngine
    engine = VisionEngine(
        source=source,
        detector=detector,
        tracker=tracker,
        config=app_config.core,
    )

    # 6. Optional Face Recognition Plugin
    if not args.no_face_recognition and not args.mock:
        logger.info("Initializing FaceRecognizerPlugin...")
        face_plugin = FaceRecognizerPlugin(config=app_config.face_recognizer)

        def _on_face_plugin_event(event: PluginEvent) -> None:
            if isinstance(event, FaceRecognizedEvent):
                logger.info(f"==> [RECOGNIZED] Track #{event.track_id} -> Employee ID: '{event.employee_id}' (sim: {event.similarity:.2f})")
            elif isinstance(event, IdentityChangedEvent):
                logger.warning(f"==> [IDENTITY CHANGED] Track #{event.track_id} switched identity: '{event.old_identity}' -> '{event.new_identity}'")
            elif isinstance(event, PersonUnknownEvent):
                logger.debug(f"[UNKNOWN] Track #{event.track_id} not matched to registered employees (sim: {event.similarity:.2f})")

        face_plugin.add_event_handler(_on_face_plugin_event)
        engine.add_listener(face_plugin)
    elif args.no_face_recognition:
        logger.info("Face recognition plugin disabled by flag (--no-face-recognition).")

    # 7. Attendance / Business Layer
    attendance_tracker = AttendanceTracker(config=app_config.attendance)

    def _on_attendance_event(event: Any) -> None:
        if isinstance(event, PersonConfirmedEvent):
            logger.info(f"[ATTENDANCE] Confirmed presence for {event.employee_id or f'Track #{event.track_id}'} ({event.duration_seconds:.1f}s)")
        elif isinstance(event, SessionWarningEvent):
            logger.warning(f"[ATTENDANCE] WARNING: Session duration exceeded threshold for {event.employee_id or f'Track #{event.track_id}'} ({event.duration_minutes:.1f}m)")
        elif isinstance(event, SessionLimitReachedEvent):
            logger.error(f"[ATTENDANCE] LIMIT: Session maximum limit reached for {event.employee_id or f'Track #{event.track_id}'} ({event.duration_minutes:.1f}m)")
        elif isinstance(event, PersonDepartedEvent):
            logger.info(f"[ATTENDANCE] Departed: {event.employee_id or f'Track #{event.track_id}'} (Total session: {event.total_session_seconds:.1f}s)")

    attendance_tracker.add_event_handler(_on_attendance_event)
    engine.add_listener(attendance_tracker)

    # 8. Visualizer Sink
    if app_config.visualizer.enabled and not args.headless:
        visualizer = OpenCVVisualizer(config=app_config.visualizer, is_headless=False)
        engine.add_sink(visualizer)

    return engine


def main() -> None:
    args = parse_args()
    logger.info("Initializing Real-Time AI Vision Engine...")
    engine = build_app(args)

    logger.info("Starting engine loop. Press Ctrl+C or 'q' in window to exit.")
    try:
        engine.start()
        frame_idx = 0
        while engine.is_running:
            frame, tracks = engine.step()
            if frame is None:
                if not engine._source.is_running:
                    logger.info("Stream ended or source closed.")
                    break
                time.sleep(0.005)
                continue

            frame_idx += 1
            if args.max_frames and frame_idx >= args.max_frames:
                logger.info(f"Reached maximum frame limit ({args.max_frames}). Stopping.")
                break

            # Log metrics periodically
            if frame_idx % 100 == 0:
                logger.info(engine.metrics.summary_str())

    except KeyboardInterrupt:
        logger.info("User requested shutdown.")
    finally:
        engine.stop()
        logger.info("Shutdown complete.")


if __name__ == "__main__":
    main()
