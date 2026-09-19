"""
The one entry point B0 delivers: play a video through the pipeline and print
tracks.

This is not the benchmark. It has no modes, no spans, no report — those are B1.
Its only job is to prove the port worked: frames go in, tracks come out, and
nothing imports a company rule on the way.

    python -m engine.tools.run --source samples/room.mp4
    python -m engine.tools.run --mock --frames 30        # no GPU, no weights
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Any, Optional, Tuple

from ..config import EngineConfig, load_config
from ..pipeline.engine import VisionEngine

logger = logging.getLogger("engine.run")


def build_source(config: EngineConfig, max_frames: Optional[int] = None) -> Any:
    """Constructs the frame source named by the config."""
    from .. import ingest

    if config.source_type == "mock":
        return ingest.MockFrameSource(max_frames=max_frames)

    if config.source_type == "video_file":
        # realtime_pacing=False: play as fast as the machine allows. B1 turns
        # this into an explicit mode choice, because throughput and realtime
        # answer different questions and must never be averaged together.
        return ingest.VideoFileSource(
            filepath=config.source_uri,
            realtime_pacing=False,
        )

    return ingest.OpenCVStreamSource(source=config.source_uri)


def build_detector(config: EngineConfig) -> Any:
    """Constructs the detector named by the config."""
    from .. import perception

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
    from .. import perception

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


def build_engine(
    config: EngineConfig,
    max_frames: Optional[int] = None,
) -> Tuple[VisionEngine, Any]:
    """Wires source, detector and tracker into a VisionEngine."""
    source = build_source(config, max_frames=max_frames)

    # The source must be OPEN before its fps is trusted. VideoFileSource sets
    # self._fps = 30.0 as a placeholder in __init__ and only learns the real
    # rate in start(); reading it early silently configures every seconds-based
    # constant against 30 fps regardless of the file. start() is idempotent, so
    # engine.start() calling it again is harmless.
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

    detector = build_detector(config)
    tracker = build_tracker(config, source_fps=source_fps)

    engine = VisionEngine(
        source=source,
        detector=detector,
        tracker=tracker,
        config=config,
    )
    return engine, source


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="engine.tools.run",
        description="Play a source through the engine pipeline and report tracks.",
    )
    parser.add_argument("--config", default=None, help="path to a YAML config")
    parser.add_argument("--source", default=None, help="override core.source_uri")
    parser.add_argument(
        "--mock",
        action="store_true",
        help="use the synthetic source, detector and tracker (no GPU, no weights)",
    )
    parser.add_argument(
        "--frames",
        type=int,
        default=None,
        help="stop after N frames",
    )
    parser.add_argument("--quiet", action="store_true", help="only print the summary")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    config = load_config(args.config)
    if args.mock:
        config = replace_source(config, source_type="mock")
    if args.source:
        config = replace_source(config, source_uri=args.source)

    engine, source = build_engine(config, max_frames=args.frames)
    _source_for_report = source
    engine.start()

    frames = 0
    seen_track_ids: set[int] = set()
    try:
        while True:
            if args.frames is not None and frames >= args.frames:
                break
            frame, tracks = engine.step()
            if frame is None:
                break
            frames += 1
            for track in tracks:
                seen_track_ids.add(track.track_id)
            if not args.quiet and frames % 50 == 0:
                logger.info("frame %d, %d live tracks", frames, len(tracks))
    finally:
        engine.stop()

    # A source that stops early must not be mistaken for a source that finished.
    # cv2.VideoCapture.read() returns None both at end-of-stream and on a decode
    # failure, and the old code logged both as "Reached end of video". A
    # benchmark computed over 6% of a file, reported as a full run, is exactly
    # the kind of flattering lie strict_mode exists to stop.
    expected = getattr(_source_for_report, "total_frames", 0) or 0
    if expected and frames < expected and args.frames is None:
        message = (
            f"source ended after {frames} of {expected} frames "
            f"({frames / expected:.1%}). This is a decode failure or a truncated "
            f"file, not a finished run — any number derived from it describes a "
            f"fraction of the source."
        )
        if config.strict_mode:
            raise RuntimeError(message)
        logger.warning("%s (strict_mode is OFF)", message)

    # Report what actually ran, not what the config asked for. A summary that
    # names the requested backend while a fallback did the work is the same
    # class of lie this step exists to remove.
    print(
        f"processed {frames} frames, {len(seen_track_ids)} distinct track ids "
        f"(source={type(source).__name__}, "
        f"detector={type(engine._detector).__name__}, "
        f"tracker={type(engine._tracker).__name__})"
    )
    return 0 if frames > 0 else 1


def replace_source(config: EngineConfig, **changes: Any) -> EngineConfig:
    """EngineConfig is frozen; this returns a copy with core fields replaced."""
    import dataclasses

    return dataclasses.replace(config, **changes)


if __name__ == "__main__":
    sys.exit(main())
