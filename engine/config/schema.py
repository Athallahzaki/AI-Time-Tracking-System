"""
Engine configuration as data.

Two rules govern this module, both from ARCHITECTURE.md §16.

1. No company policy lives here. There is no break allowance, no working
   hours, no warning threshold. The engine may only hold *perceptual*
   constants: how long before a track is considered gone, how much evidence
   before an identity is confirmed, what similarity counts as a match. The
   `attendance:` block of the old configs/default_config.yaml is therefore not
   ported — it is dead, and its replacement is born in backend/policy/.
   contracts/tools/policy_grep.py enforces this in CI.

2. Every temporal parameter is expressed in SECONDS and converted to frames at
   construction time using the effective fps. The old code hardcoded
   frame_rate=30 and track_buffer=30 inside ByteTrackTracker; at 10 fps that
   buffer silently changes meaning from 1 second to 3 seconds and the Kalman
   motion model is miscalibrated. Converting the unit is behaviour-preserving
   at 30 fps, which is why it belongs to B0; dropping to 10 fps is a separate,
   measured step.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union


def resolve_engine_path(raw_path: Union[str, Path]) -> str:
    """
    Resolves a relative file or directory path within the project.

    Checks, in order: the path as given, relative to the engine root, and
    relative to the workspace root.
    """
    p = Path(raw_path)
    if p.exists():
        return str(p.resolve())

    engine_root = Path(__file__).resolve().parents[1]  # engine/
    candidate = engine_root / p
    if candidate.exists():
        return str(candidate.resolve())

    if str(p).startswith("engine/") or str(p).startswith("engine\\"):
        sub_p = Path(*p.parts[1:])
        candidate = engine_root / sub_p
        if candidate.exists():
            return str(candidate.resolve())

    workspace_root = engine_root.parent
    candidate = workspace_root / p
    if candidate.exists():
        return str(candidate.resolve())

    return str(p)


def seconds_to_frames(seconds: float, fps: float) -> int:
    """
    Converts a temporal constant in seconds to whole frames at a given fps.

    Rounds up and never returns less than 1: a buffer of zero frames means a
    track dies the instant it is occluded, which is never what a duration in
    seconds was meant to express.
    """
    if fps <= 0.0:
        raise ValueError(f"fps must be positive, got {fps}")
    if seconds < 0.0:
        raise ValueError(f"duration must not be negative, got {seconds}")
    return max(1, int(math.ceil(seconds * fps)))


@dataclass(frozen=True)
class TrackerConfig:
    """Perceptual constants for the tracker. Nothing here is a company rule."""

    backend: str = "bytetrack"          # "bytetrack" | "iou"
    track_threshold: float = 0.45
    match_threshold: float = 0.8
    track_buffer_seconds: float = 1.0   # was track_buffer=30 frames at 30 fps

    def track_buffer_frames(self, fps: float) -> int:
        return seconds_to_frames(self.track_buffer_seconds, fps)

    def __post_init__(self) -> None:
        if self.backend not in ("bytetrack", "iou"):
            raise ValueError(
                f"Unknown tracker backend '{self.backend}'. "
                f"Expected 'bytetrack' or 'iou'."
            )


@dataclass(frozen=True)
class DetectorConfig:
    """Perceptual constants for the object detector."""

    model_path: str = "LibreDFINEs.pt"
    confidence_threshold: float = 0.50
    iou_threshold: float = 0.45
    image_size: int = 640
    device: Union[str, int] = "auto"
    half: bool = False


@dataclass(frozen=True)
class EngineConfig:
    """
    Top-level engine configuration.

    `strict_mode` is the one setting here that changes behaviour, and it changes
    it from "silently wrong" to "loudly broken". See config/loader.py.
    """

    source_uri: str = "0"
    source_type: str = "opencv"         # opencv | video_file | mock
    detection_interval: int = 1
    target_fps: Optional[float] = None
    auto_warmup: bool = True
    strict_mode: bool = True

    detector: DetectorConfig = field(default_factory=DetectorConfig)
    tracker: TrackerConfig = field(default_factory=TrackerConfig)

    def effective_fps(self, source_fps: float) -> float:
        """
        The fps the pipeline actually runs at — used for every seconds-to-frames
        conversion. target_fps caps the source; it never raises it.
        """
        if self.target_fps is None:
            return source_fps
        if source_fps <= 0.0:
            return self.target_fps
        return min(self.target_fps, source_fps)

    def __post_init__(self) -> None:
        if self.detection_interval < 1:
            raise ValueError(
                f"detection_interval must be >= 1, got {self.detection_interval}."
            )
        if self.source_type not in ("opencv", "video_file", "mock"):
            raise ValueError(f"Unknown source_type '{self.source_type}'.")
