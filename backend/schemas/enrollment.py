from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from backend.schemas.employee import _tolak_anon


class EnrollmentImageInput(BaseModel):
    """A single image to enroll."""

    id: str
    jpeg_b64: str


class EnrollmentRequest(BaseModel):
    """Enrollment request from the frontend."""

    person_id: str
    images: List[EnrollmentImageInput]

    # P10: ANON- milik kelompok ReID; mendaftarkan wajah ke sana mencampur dua ruang identitas.
    _person_id_bukan_anon = field_validator("person_id")(_tolak_anon)


class EnrollmentImageResult(BaseModel):
    """Per-image result from the enrollment pipeline."""

    image_id: str
    accepted: bool
    quality: float = 0.0
    reason: Optional[str] = None
    similarity: Optional[float] = None


class EnrollmentResult(BaseModel):
    """Full enrollment result returned to the frontend."""

    person_id: str
    accepted: bool
    reason: Optional[str] = None
    collides_with: Optional[str] = None
    collision_similarity: Optional[float] = None
    images: List[EnrollmentImageResult] = Field(default_factory=list)


class EnrolledPerson(BaseModel):
    """Summary of an enrolled person."""

    person_id: str
    enrollment_version: int
    reference_count: int = 0
    enrolled_at: Optional[str] = None
    last_seen_at: Optional[str] = None