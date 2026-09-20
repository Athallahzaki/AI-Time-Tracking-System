"""
Wiring: config in, running engine out.

These four functions were `engine/tools/run.py` in B0 and moved here unchanged
in B1, because two callers now need them — the CLI and the benchmark's stream
adapter — and having the adapter import from `tools/` would be backwards. No
behaviour changed in the move; `tests/test_b0_port.py` still covers it.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional, Tuple

from .config import EngineConfig
from .pipeline.instrument import Recorder

logger = logging.getLogger("engine.factory")

# Applied to the source after its fps is known, before the engine is built.
# The benchmark uses it to insert realtime pacing; nothing else should.
SourceWrapper = Callable[[Any, float], Any]


def build_source(
    config: EngineConfig,
    max_frames: Optional[int] = None,
    source_id: Optional[str] = None,
) -> Any:
    """Constructs the frame source named by the config."""
    from . import ingest

    uri = config.source_uri
    is_network = uri.lower().startswith(
        ("rtsp://", "rtsps://", "rtmp://", "http://", "https://", "udp://")
    )
    # PyAV takes files and network streams. A bare device index ("0" for a
    # webcam) needs a platform-specific input format, which is a different
    # problem and not what B4 is for — those still go to the OpenCV source.
    use_pyav = config.ingest.backend == "pyav" and (
        config.source_type == "video_file" or is_network
    )

    if config.source_type == "mock":
        source = ingest.MockFrameSource(max_frames=max_frames)
    elif use_pyav:
        # One source class for files and for RTSP: PyAV does not care, and the
        # difference that used to justify two classes — reconnect — is a config
        # flag rather than a type (§5.5).
        source = ingest.PyAVSource(
            uri=config.source_uri,
            rtsp_transport=config.ingest.rtsp_transport,
            timeout_seconds=config.ingest.timeout_seconds,
            reconnect_attempts=config.ingest.reconnect_attempts,
            reconnect_backoff_seconds=config.ingest.reconnect_backoff_seconds,
            max_reconnect_backoff_seconds=(
                config.ingest.max_reconnect_backoff_seconds
            ),
            measure_timeline_fidelity=config.ingest.measure_timeline_fidelity,
            decoder_thread_type=config.ingest.decoder_thread_type,
            decoder_threads=config.ingest.decoder_threads,
        )
    elif config.source_type == "video_file":
        # realtime_pacing=False always. Pacing is a benchmark mode decision
        # (§13.2) and it is made one layer up, by wrapping this source, so that
        # throughput and realtime never differ by a constructor argument
        # somebody forgot to pass.
        source = ingest.VideoFileSource(
            filepath=config.source_uri,
            realtime_pacing=False,
        )
    else:
        if config.ingest.backend == "pyav":
            logger.warning(
                "ingest.backend is 'pyav' but %r is a device index, not a file "
                "or a stream URL. Falling back to the OpenCV source, which has "
                "no container PTS — every timestamp from this run is derived "
                "from the frame index (§5.5), and the report says so.",
                config.source_uri,
            )
        source = ingest.OpenCVStreamSource(source=config.source_uri)

    if source_id is not None:
        source._source_id = source_id
    return source


def build_detector(config: EngineConfig) -> Any:
    """Constructs the detector named by the config."""
    from . import perception

    if config.source_type == "mock":
        return perception.MockDetector()

    return perception.YOLODetector(
        model_path=config.detector.model_path,
        confidence_threshold=config.detector.confidence_threshold,
        iou_threshold=config.detector.iou_threshold,
        image_size=config.detector.image_size,
        device=config.detector.device,
        half=config.detector.half,
    )


def build_tracker(config: EngineConfig, source_fps: float) -> Any:
    """
    Constructs the tracker named by the config.

    This is where seconds become frames. The old code hardcoded 30 in two
    places; here the effective fps decides, so dropping to 10 fps later changes
    the frame count and leaves the *meaning* of the constant intact.
    """
    from . import perception

    if config.source_type == "mock":
        return perception.MockTracker()

    fps = config.effective_fps(source_fps)
    buffer_frames = config.tracker.track_buffer_frames(fps)

    logger.info(
        "Tracker '%s': source %.2f fps, target %s -> effective %.2f fps; "
        "track_buffer %.2fs = %d frames",
        config.tracker.backend,
        source_fps,
        f"{config.target_fps:.2f}" if config.target_fps is not None else "none",
        fps,
        config.tracker.track_buffer_seconds,
        buffer_frames,
    )

    if config.tracker.backend == "iou":
        return perception.IoUTracker(max_missing_frames=buffer_frames)

    return perception.ByteTrackTracker(
        track_thresh=config.tracker.track_threshold,
        match_thresh=config.tracker.match_threshold,
        track_buffer=buffer_frames,
        frame_rate=int(round(fps)),
        strict=config.strict_mode,
    )


def resolve_source_fps(config: EngineConfig, source: Any) -> float:
    """
    The fps every seconds-to-frames conversion is done against.

    The source must be OPEN before its fps is trusted. VideoFileSource sets
    self._fps = 30.0 as a placeholder in __init__ and only learns the real rate
    in start(); reading it early silently configures every seconds-based
    constant against 30 fps regardless of the file. start() is idempotent, so
    engine.start() calling it again is harmless.
    """
    if config.source_type != "mock":
        source.start()
    source_fps = float(getattr(source, "fps", 0.0) or 0.0)

    if source_fps <= 0.0 and config.source_type != "mock":
        # Never guess. Every temporal constant is in seconds and converted with
        # this number; a fabricated fps miscalibrates the tracker's motion model
        # without producing a single error.
        if config.target_fps is None:
            raise RuntimeError(
                f"Source {type(source).__name__} reports fps={source_fps}. "
                "Temporal constants are expressed in seconds and converted with "
                "it, so guessing here would silently miscalibrate the tracker. "
                "Set core.target_fps explicitly if the source cannot report its "
                "rate."
            )
        source_fps = config.target_fps

    return source_fps


def build_engine(
    config: EngineConfig,
    max_frames: Optional[int] = None,
    recorder: Optional[Recorder] = None,
    source_id: Optional[str] = None,
    wrap_source: Optional[SourceWrapper] = None,
) -> Tuple[Any, Any, float]:
    """
    Wires source, detector and tracker into a VisionEngine.

    Returns the engine, the *innermost* source (so callers can read
    total_frames off it) and the resolved source fps.

    The VisionEngine import is deliberately inside the function. `build_detector`
    is called by the benchmark's detector-throughput probe, and §13.9 asks that
    nothing on the bench's side pull `pipeline` in as a side effect of importing
    a builder.
    """
    from .pipeline.engine import VisionEngine
    source = build_source(config, max_frames=max_frames, source_id=source_id)
    source_fps = resolve_source_fps(config, source)

    detector = build_detector(config)
    tracker = build_tracker(config, source_fps=source_fps)

    engine_source = source if wrap_source is None else wrap_source(source, source_fps)

    engine = VisionEngine(
        source=engine_source,
        detector=detector,
        tracker=tracker,
        config=config,
        recorder=recorder,
    )
    return engine, source, source_fps
