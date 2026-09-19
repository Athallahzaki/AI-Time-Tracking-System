"""Camera-related API schemas."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class CameraStatus(BaseModel):
    """Status of a single camera as seen by the backend."""
    camera_id: str
    name: str = ""
    uri: str = ""
    stream_url: str = ""
    door_region: Optional[List[float]] = None  # [x1,y1,x2,y2] normalised
    enabled: bool = True
    # Runtime status (from engine events)
    status: str = "unknown"   # "online" | "failed" | "degraded" | "unknown"
    fps: float = 0.0
    failure_reason: Optional[str] = None
    # Live tracking
    active_tracks: int = 0
    identified_persons: int = 0


class SetCamerasRequest(BaseModel):
    """Declarative camera configuration — PUT /api/cameras.

    This is the *entire* desired set of cameras. Cameras not in this list
    will be stopped. This mirrors the protocol's set_cameras semantics.
    """

    class CameraEntry(BaseModel):
        camera_id: str
        name: str = ""
        uri: str
        stream_url: str = ""
        door_region: Optional[List[float]] = None
        enabled: bool = True

    cameras: List[CameraEntry]


class SetRosterRequest(BaseModel):
    """Declarative roster — PUT /api/roster.

    Mirrors protocol set_roster. Only IDs and versions; embeddings stay
    in engine.
    """

    class PersonEntry(BaseModel):
        person_id: str
        enrollment_version: int = 1

    persons: List[PersonEntry]
