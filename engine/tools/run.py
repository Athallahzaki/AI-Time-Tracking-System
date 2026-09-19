"""
The one entry point B0 delivers: play a video through the pipeline and print
tracks.

This is not the benchmark. It has no modes, no spans, no report — those are
`python -m engine.bench`. Its only job is to prove the wiring works: frames go
in, tracks come out, and nothing imports a company rule on the way.

    python -m engine.tools.run --source samples/room.mp4
    python -m engine.tools.run --mock --frames 30        # no GPU, no weights

Since B1 it drives the same `TrackStream` the benchmark does, so there is one
frame loop and one truncated-source check in the codebase rather than two that
drift apart.
"""

from __future__ import annotations

import argparse
import dataclasses
import logging
import sys
from typing import Any, Optional

from ..config import EngineConfig, load_config

logger = logging.getLogger("engine.run")


def replace_source(config: EngineConfig, **changes: Any) -> EngineConfig:
    """EngineConfig is frozen; this returns a copy with core fields replaced."""
    return dataclasses.replace(config, **changes)


def main(argv: Optional[list[str]] = None) -> int:
    from ..streams.local import LocalTrackStream

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
    parser.add_argument("--frames", type=int, default=None, help="stop after N frames")
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

    stream = LocalTrackStream(config, camera_id="cam0", max_frames=args.frames)
    descriptor = stream.open()

    frames = 0
    seen_track_ids: set[int] = set()
    try:
        for observation in stream.observations():
            frames += 1
            for track in observation.tracks:
                seen_track_ids.add(track.track_id)
            if not args.quiet and frames % 50 == 0:
                logger.info(
                    "frame %d, %d live tracks", frames, len(observation.tracks)
                )
    finally:
        stream.close()

    # Report what actually ran, not what the config asked for. A summary that
    # names the requested backend while a fallback did the work is the same
    # class of lie this step exists to remove.
    print(
        f"processed {frames} frames, {len(seen_track_ids)} distinct track ids "
        f"(source={descriptor.source_class}, "
        f"detector={descriptor.detector_class}, "
        f"tracker={descriptor.tracker_class})"
    )
    return 0 if frames > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
