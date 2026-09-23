"""Pydantic models for the NDJSON Engine Protocol (ENGINE_PROTOCOL.md).

These are used by protocol_client.py to validate incoming/outgoing messages.
Every message type from §2-5 of the protocol spec is represented here.

Convention:
  - All *_pts fields are in seconds (float), relative to stream start.
  - All *_at fields are RFC3339 UTC strings.
  - bbox is normalised [x1, y1, x2, y2] in 0-1 range.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field


# ── Enums ────────────────────────────────────────────────────────────────────

class EndReason(str, Enum):
    LEFT_FRAME = "left_frame"
    OCCLUDED_TIMEOUT = "occluded_timeout"
    MERGED_INTO_OTHER_TRACK = "merged_into_other_track"
    CAMERA_LOST = "camera_lost"
    ENGINE_SHUTDOWN = "engine_shutdown"
    IDENTITY_RELEASED = "identity_released"


class Zone(str, Enum):
    DOOR = "door"
    INTERIOR = "interior"
    FRAME_EDGE = "frame_edge"


class BoundarySource(str, Enum):
    FACE = "face"
    TRACKING = "tracking"
    FORCED = "forced"


class IdentitySource(str, Enum):
    FACE = "face"
    TRACKING = "tracking"


class UnidentifiedReason(str, Enum):
    NO_FACE_DETECTED = "no_face_detected"
    QUALITY_GATE_REJECTED = "quality_gate_rejected"
    BELOW_THRESHOLD = "below_threshold"
    MARGIN_TOO_NARROW = "margin_too_narrow"


class ImageRejectionReason(str, Enum):
    TOO_SMALL = "too_small"
    BLURRY = "blurry"
    EXTREME_POSE = "extreme_pose"
    BAD_LIGHTING = "bad_lighting"
    NO_FACE = "no_face"
    MULTIPLE_FACES = "multiple_faces"
    # duplicate_of:<id> is handled as string prefix


class EnrollmentRejectionReason(str, Enum):
    COLLISION = "collision"
    INSUFFICIENT_REFERENCES = "insufficient_references"
    OK = "ok"


# ── Shared envelope ──────────────────────────────────────────────────────────

class BaseMessage(BaseModel):
    """Common fields on every protocol message."""
    type: str
    v: int = 1
    ts: Optional[str] = None  # RFC3339 UTC

    model_config = {"extra": "allow"}  # ignore unknown fields per protocol rule


class SequencedMessage(BaseMessage):
    """Messages on the events channel carry a monotonic sequence number."""
    seq: int


# ── Control channel (Backend → Engine) ───────────────────────────────────────

class HelloMessage(BaseMessage):
    type: str = "hello"
    protocol_version: int = 1
    client: str = "backend-py/1.0.0"
    last_event_seq: int = 0


class CameraSpec(BaseModel):
    camera_id: str
    uri: str
    door_region: Optional[List[float]] = None  # [x1, y1, x2, y2] normalised
    enabled: bool = True


class SetCamerasMessage(BaseMessage):
    type: str = "set_cameras"
    cameras: List[CameraSpec]


class RosterPerson(BaseModel):
    person_id: str
    enrollment_version: int


class SetRosterMessage(BaseMessage):
    type: str = "set_roster"
    persons: List[RosterPerson]


class EnrollImage(BaseModel):
    id: str
    jpeg_b64: str


class EnrollMessage(BaseMessage):
    type: str = "enroll"
    request_id: str
    person_id: str
    enrollment_version: int
    images: List[EnrollImage]


# ── Events channel (Engine → Backend) ────────────────────────────────────────

class HelloAckMessage(BaseMessage):
    type: str = "hello_ack"
    protocol_version: int = 1
    engine_version: str = ""
    models: Dict[str, str] = {}
    oldest_available_seq: int = 0


class AckMessage(BaseMessage):
    type: str = "ack"
    in_reply_to: str
    accepted: bool


class ReplayGapMessage(BaseMessage):
    type: str = "replay_gap"
    from_seq: int
    to_seq: int


# Events: presence.interval — primary output
class PresenceIntervalEvent(SequencedMessage):
    type: str = "presence.interval"
    interval_id: str
    person_id: str
    camera_id: str
    start_pts: float
    end_pts: float
    start_at: str  # RFC3339
    end_at: str    # RFC3339
    start_source: BoundarySource
    end_source: BoundarySource
    start_zone: Zone
    end_zone: Zone
    end_reason: EndReason
    identity_confidence: float = 0.0
    evidence_count: int = 0
    prev_interval_id: Optional[str] = None
    evidence_crop: Optional[Dict[str, str]] = None


# Events: track lifecycle
class TrackStartedEvent(SequencedMessage):
    type: str = "track.started"
    track_uuid: str
    camera_id: str
    pts: float
    zone: Zone


class TrackIdentifiedEvent(SequencedMessage):
    type: str = "track.identified"
    track_uuid: str
    person_id: str
    pts: float
    track_started_pts: float
    similarity: float
    margin: float
    evidence_count: int


class TrackHeartbeatEvent(SequencedMessage):
    type: str = "track.heartbeat"
    track_uuid: str
    person_id: Optional[str] = None
    pts: float
    identity_source: IdentitySource
    confidence: float


class TrackResumedEvent(SequencedMessage):
    type: str = "track.resumed"
    track_uuid: str
    prev_track_uuid: str
    person_id: Optional[str] = None
    gap_seconds: float
    pts: float


class TrackIdentityChangedEvent(SequencedMessage):
    type: str = "track.identity_changed"
    track_uuid: str
    from_person_id: Optional[str] = None
    to_person_id: Optional[str] = None
    reason: str
    disagreement_count: int = 0


class TrackEndedEvent(SequencedMessage):
    type: str = "track.ended"
    track_uuid: str
    pts: float
    reason: EndReason
    exit_zone: Zone


# Events: operational signals
class UnidentifiedPresentEvent(SequencedMessage):
    type: str = "person.unidentified_present"
    track_uuid: str
    camera_id: str
    duration_seconds: float
    attempts: int
    reason: UnidentifiedReason


# Events: camera status
class CameraOnlineEvent(SequencedMessage):
    type: str = "camera.online"
    camera_id: str
    fps: float = 0.0


class CameraFailedEvent(SequencedMessage):
    type: str = "camera.failed"
    camera_id: str
    reason: str
    retry_in_seconds: float = 5.0


class CameraDegradedEvent(SequencedMessage):
    type: str = "camera.degraded"
    camera_id: str
    reason: str
    fps: float = 0.0


class CameraCoverageEvent(SequencedMessage):
    type: str = "camera.coverage"
    camera_id: str
    observed_regions: List[List[float]] = []
    never_observed: List[List[float]] = []


# Events: engine health
class EngineHealthEvent(SequencedMessage):
    type: str = "engine.health"
    models_loaded: bool = False
    gpu_util: float = 0.0
    vram_mb: float = 0.0
    queue_depth: int = 0
    drop_rate: float = 0.0
    cameras: Dict[str, str] = {}


# Events: snapshot
class SnapshotLiveTrack(BaseModel):
    track_uuid: str
    camera_id: str
    stream_epoch: int
    person_id: Optional[str] = None
    identity_source: Optional[IdentitySource] = None
    since_pts: float


class SnapshotClock(BaseModel):
    stream_epoch: int
    offset: float


class SnapshotEvent(SequencedMessage):
    type: str = "snapshot"
    pts_wallclock_offset: Dict[str, SnapshotClock] = Field(default_factory=dict)
    live: List[SnapshotLiveTrack] = Field(default_factory=list)


# Events: enrollment
class EnrollmentNeededEvent(SequencedMessage):
    type: str = "enrollment_needed"
    person_ids: List[str]


class EnrollImageResult(BaseModel):
    id: str
    accepted: bool
    quality: float = 0.0
    reason: Optional[str] = None
    similarity: Optional[float] = None


class EnrollResultEvent(BaseMessage):
    type: str = "enroll_result"
    request_id: str
    accepted: bool
    reason: Optional[str] = None
    collides_with: Optional[str] = None
    collision_similarity: Optional[float] = None
    images: List[EnrollImageResult] = []


# ── View channel (Engine → Backend, best-effort) ────────────────────────────

class ViewBox(BaseModel):
    track_uuid: str
    bbox: List[float]  # [x1, y1, x2, y2] normalised 0-1
    person_id: Optional[str] = None
    identity_source: Optional[IdentitySource] = None
    session_elapsed: Optional[float] = None
    dwell_time: Optional[float] = None
    is_official_break: Optional[bool] = None
    is_qualified: Optional[bool] = None
    qualification_seconds: Optional[float] = None
    qualification_remaining_seconds: Optional[float] = None
    visit_free_time_seconds: Optional[float] = None
    daily_used_seconds: Optional[float] = None
    remaining_seconds: Optional[float] = None
    allowance_seconds: Optional[float] = None
    presence_status: Optional[str] = None


class ViewFrameMessage(BaseMessage):
    type: str = "view.frame"
    camera_id: str
    pts: float
    boxes: List[ViewBox] = []


# ── Event type registry ──────────────────────────────────────────────────────

EVENT_TYPE_MAP: Dict[str, type] = {
    # Control responses
    "hello_ack": HelloAckMessage,
    "ack": AckMessage,
    "replay_gap": ReplayGapMessage,
    # Domain events
    "presence.interval": PresenceIntervalEvent,
    "track.started": TrackStartedEvent,
    "track.identified": TrackIdentifiedEvent,
    "track.heartbeat": TrackHeartbeatEvent,
    "track.resumed": TrackResumedEvent,
    "track.identity_changed": TrackIdentityChangedEvent,
    "track.ended": TrackEndedEvent,
    "person.unidentified_present": UnidentifiedPresentEvent,
    # Camera / engine
    "camera.online": CameraOnlineEvent,
    "camera.failed": CameraFailedEvent,
    "camera.degraded": CameraDegradedEvent,
    "camera.coverage": CameraCoverageEvent,
    "engine.health": EngineHealthEvent,
    "snapshot": SnapshotEvent,
    # Enrollment
    "enrollment_needed": EnrollmentNeededEvent,
    "enroll_result": EnrollResultEvent,
    # View
    "view.frame": ViewFrameMessage,
}


def parse_message(raw: Dict[str, Any]) -> BaseMessage:
    """Parse a raw dict into the appropriate protocol message type.

    Unknown message types are returned as BaseMessage (unknown fields preserved
    via extra="allow"), per protocol rule: unknown fields are silently ignored.
    """
    msg_type = raw.get("type", "")
    model_cls = EVENT_TYPE_MAP.get(msg_type, BaseMessage)
    return model_cls.model_validate(raw)
