"""Enrollment API schemas.

These mirror the protocol's enroll / enroll_result messages but are shaped
for the REST API that the frontend consumes.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


class EnrollmentImageResult(BaseModel):
    """Per-image result from the engine's enrollment pipeline."""
    image_id: str
    accepted: bool
    quality: float = 0.0
    reason: Optional[str] = None  # too_small, blurry, extreme_pose, ...
    similarity: Optional[float] = None  # if duplicate


class EnrollmentResult(BaseModel):
    """Full enrollment result returned to the frontend."""
    person_id: str
    accepted: bool
    reason: Optional[str] = None  # collision, insufficient_references, ok
    collides_with: Optional[str] = None
    collision_similarity: Optional[float] = None
    images: List[EnrollmentImageResult] = []


class EnrollmentRequest(BaseModel):
    """Enrollment request from the frontend.

    Images are sent as base64-encoded JPEGs. The frontend does the encoding;
    the backend forwards to the engine as-is.
    """
    person_id: str
    images: List[EnrollmentImageInput]


class EnrollmentImageInput(BaseModel):
    """A single image to enroll."""
    id: str
    jpeg_b64: str


# Fix forward reference
EnrollmentRequest.model_rebuild()


class EnrolledPerson(BaseModel):
    """Summary of an enrolled person."""
    person_id: str
    enrollment_version: int
    reference_count: int = 0
    enrolled_at: Optional[str] = None
    last_seen_at: Optional[str] = None
