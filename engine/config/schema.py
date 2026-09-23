"""
Engine configuration as data.

Two rules govern this module, both from ARCHITECTURE.md §16.

1. No company rule lives here. The engine may only hold *perceptual*
   constants: how long before a track is considered gone, how much evidence
   before an identity is confirmed, what similarity counts as a match. The
   section of the old configs/default_config.yaml that encoded office rules was
   therefore not ported — it is dead, and its replacement is born in
   backend/policy/. config/loader.py enforces this by accepting only the fields
   declared below, and contracts/tools/policy_grep.py enforces it in CI.

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
from typing import Optional, Tuple, Union


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

    backend: str = "iou"                # "bytetrack" | "iou"
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
class IngestConfig:
    """
    How frames get in, and on what timeline (ARCHITECTURE.md §5.5).

    `backend` exists for one step only. B4 replaces OpenCV ingest with PyAV so
    that PTS is real rather than derived from a frame index, and a swap that
    large gets measured rather than asserted: the same recording is benched on
    both and the delta is committed. After that, `opencv` goes away.
    """

    backend: str = "pyav"              # "pyav" | "opencv"
    rtsp_transport: str = "tcp"        # UDP corrupts frames silently (§5.5)
    timeout_seconds: float = 8.0       # a dead camera must not hang a thread
    reconnect_attempts: int = 0        # 0 for files; a live camera wants > 0
    reconnect_backoff_seconds: float = 1.0
    max_reconnect_backoff_seconds: float = 30.0
    measure_timeline_fidelity: bool = True

    # Decoder threading. "AUTO" is frame + slice threading, which is what
    # FFmpeg gives OpenCV by default and what a 1080p HEVC stream needs to keep
    # up. Frame threading buffers a few frames inside the decoder, which costs
    # a little delivery latency on a live camera but changes no timestamp: PTS
    # travels with the frame. "SLICE" avoids that buffering if it ever matters;
    # "NONE" is for proving what single-threaded decode actually costs.
    decoder_thread_type: str = "AUTO"    # "AUTO" | "SLICE" | "FRAME" | "NONE"
    decoder_threads: int = 0             # 0 = one per core

    # How a decoded frame becomes a BGR ndarray. Two routes with identical
    # output, kept switchable only because `probe_ingest` measured PyAV 29%
    # behind OpenCV on the same file and a suspect is worth timing rather than
    # arguing about. Default stays on the one B4 shipped so the committed
    # baseline does not move; the switch happens in its own commit if and when
    # the probe says it is worth something (§16).
    colour_conversion: str = "to_ndarray"   # "to_ndarray" | "reformatter"

    def __post_init__(self) -> None:
        if self.colour_conversion not in ("to_ndarray", "reformatter"):
            raise ValueError(
                f"Unknown ingest.colour_conversion '{self.colour_conversion}'. "
                f"Expected 'to_ndarray' or 'reformatter'."
            )
        if self.decoder_thread_type not in ("AUTO", "SLICE", "FRAME", "NONE"):
            raise ValueError(
                f"Unknown decoder_thread_type '{self.decoder_thread_type}'. "
                f"Expected AUTO, SLICE, FRAME or NONE."
            )
        if self.backend not in ("pyav", "opencv"):
            raise ValueError(
                f"Unknown ingest backend '{self.backend}'. Expected 'pyav' or "
                f"'opencv'."
            )
        if self.timeout_seconds <= 0:
            raise ValueError("ingest.timeout_seconds must be positive.")


@dataclass(frozen=True)
class ZoneConfig:
    """
    Where the door is, per camera, in normalized coordinates (B5, §3.2, §4.2).

    **This is the local path, not the production one.** At runtime `door_region`
    arrives from the backend in `set_cameras` (ENGINE_PROTOCOL.md §3.2) and the
    wire always wins: a camera can be moved without touching a config file, and
    two sources of truth for where the door is would eventually disagree about
    whether somebody left the room. What this section is for is the single-camera
    developer run and the benchmark, where there is no backend to ask — and
    without it the benchmark cannot compute §13.8's cheap false-gap estimate,
    which is defined in terms of the door region.

    Normalized because the engine sees the mainstream and whoever draws the
    region is looking at the dashboard's substream (§6.7.2). In pixels the region
    would land somewhere else at a different resolution, and silently.

    Nothing here is a company rule: a door is a fact about a room, `edge_margin`
    is a fact about geometry, and neither knows what a break is.
    """

    door_regions: dict = field(default_factory=dict)   # camera_id -> [x1,y1,x2,y2]
    edge_margin: float = 0.03

    def __post_init__(self) -> None:
        if not isinstance(self.door_regions, dict):
            raise ValueError(
                "zones.door_regions must be a mapping of camera_id -> "
                "[x1, y1, x2, y2] normalized to 0-1."
            )
        if not (0.0 <= self.edge_margin < 0.5):
            raise ValueError(
                f"zones.edge_margin must be in [0, 0.5), got {self.edge_margin}."
            )
        # Validated here rather than at first use: a malformed region would
        # otherwise surface halfway through a long run, after the recording it
        # was supposed to label is already half processed.
        from ..presence.zones import DoorRegion

        for camera_id, values in self.door_regions.items():
            try:
                DoorRegion.from_sequence(values)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"zones.door_regions['{camera_id}']: {exc}") from exc


@dataclass(frozen=True)
class RecognitionConfig:
    """
    The recognition queue's perceptual constants (B5, §3.2, §5.2).

    `enabled` defaults to **false**, and that is not timidity. B1's baseline was
    measured with no scheduler in the loop; turning one on by default would move
    the numbers every later step is compared against, in the same commit that
    introduced it. It is switched on for the runs that are about it.

    Every other value defaults to `None`, meaning "whatever
    `identity/admission.py` says". Copying those numbers here would give each of
    them two homes and one day two values — and the one in the config file would
    win while the docstring explaining it stayed next to the other.
    """

    enabled: bool = False
    max_age_seconds: Optional[float] = None
    retry_interval_seconds: Optional[float] = None
    reverify_interval_seconds: Optional[float] = None
    per_camera_quota: Optional[int] = None

    # How many requests the frame loop hands out per frame. The loop is still
    # synchronous: until the worker pool of §5.2 exists there is nothing to
    # overlap with, so this is a throttle on bookkeeping, not on GPU work.
    max_requests_per_frame: int = 2

    # --- the recognizer slot --------------------------------------------
    # "none" (default): no face model is loaded, enrollment answers
    # `recognizer_disabled`, every track stays nameless. "onnx_face": SCRFD +
    # AuraFace through onnxruntime (engine/identity/face_onnx.py). Turning it
    # on also requires `enabled: true` — recognition needs the scheduler.
    recognizer: str = "none"
    face_detector_model: Optional[str] = None
    face_embedder_model: Optional[str] = None
    embedding_version: str = "auraface-v1"
    reference_db_path: str = "engine/data/references.sqlite3"
    onnx_providers: Optional[Tuple[str, ...]] = None
    face_detection_threshold: float = 0.5
    min_face_px: float = 40.0
    match_threshold: Optional[float] = None
    match_margin: Optional[float] = None

    def __post_init__(self) -> None:
        if self.recognizer not in ("none", "onnx_face"):
            raise ValueError("recognition.recognizer must be 'none' or 'onnx_face'.")
        if self.recognizer != "none" and not self.enabled:
            raise ValueError(
                "recognition.recognizer is set but recognition.enabled is false; "
                "a recognizer without the scheduler would never be asked anything."
            )
        if self.recognizer != "none" and not (self.face_detector_model and self.face_embedder_model):
            raise ValueError(
                "recognition.recognizer=onnx_face needs face_detector_model and face_embedder_model."
            )
        if self.max_requests_per_frame < 0:
            raise ValueError("recognition.max_requests_per_frame must be >= 0.")
        for name in ("max_age_seconds", "retry_interval_seconds",
                     "reverify_interval_seconds"):
            value = getattr(self, name)
            if value is not None and value <= 0:
                raise ValueError(f"recognition.{name} must be positive if set.")
        if self.per_camera_quota is not None and self.per_camera_quota < 1:
            raise ValueError("recognition.per_camera_quota must be >= 1 if set.")

    def scheduler_kwargs(self) -> dict:
        """Only the values actually set, so the scheduler's own defaults apply."""
        mapping = {
            "max_age_seconds": self.max_age_seconds,
            "retry_interval_seconds": self.retry_interval_seconds,
            "reverify_interval_seconds": self.reverify_interval_seconds,
            "per_camera_quota": self.per_camera_quota,
        }
        return {key: value for key, value in mapping.items() if value is not None}


@dataclass(frozen=True)
class DetectorConfig:
    """Perceptual constants for the object detector."""

    model_path: str = "LibreDFINEn.pt"
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

    ingest: IngestConfig = field(default_factory=IngestConfig)
    detector: DetectorConfig = field(default_factory=DetectorConfig)
    tracker: TrackerConfig = field(default_factory=TrackerConfig)
    zones: ZoneConfig = field(default_factory=ZoneConfig)
    recognition: RecognitionConfig = field(default_factory=RecognitionConfig)

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
