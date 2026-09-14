from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class EnrollmentResult:
    """
    Result of registering face references for an identity.
    """

    identity_id: str
    success: bool

    images_processed: int
    images_accepted: int
    images_rejected: int

    errors: List[str] = field(default_factory=list)