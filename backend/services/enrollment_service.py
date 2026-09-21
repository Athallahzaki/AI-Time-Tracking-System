from __future__ import annotations

from typing import Any, Dict
from uuid import uuid4

from backend.services.protocol_adapter import protocol_adapter
from backend.core.database import create_enrollment
from backend.schemas.enrollment import EnrollmentRequest
from backend.schemas.protocol import EnrollMessage


class EnrollmentService:
    def __init__(self) -> None:
        self._pending: Dict[str, Dict[str, Any]] = {}

    def create_request(
        self,
        request: EnrollmentRequest,
    ) -> EnrollMessage:
        if not request.images:
            raise ValueError(
                "At least one enrollment image is required"
            )

        request_id = f"enroll_{uuid4().hex}"

        message = EnrollMessage(
            type="enroll",
            v=1,
            request_id=request_id,
            person_id=request.person_id,
            enrollment_version=1,
            images=[
                {
                    "id": image.id,
                    "jpeg_b64": image.jpeg_b64,
                }
                for image in request.images
            ],
        )

        # Pending only.
        # Belum boleh masuk SQLite sebelum enroll_result.
        self._pending[request_id] = {
            "person_id": request.person_id,
            "reference_count": len(request.images),
        }

        return message

    def handle_result(
        self,
        result: Dict[str, Any],
    ) -> Dict[str, Any]:
        if result.get("type") != "enroll_result":
            raise ValueError(
                "Expected enroll_result"
            )

        request_id = result.get("request_id")

        pending = self._pending.get(request_id)

        if pending is None:
            raise ValueError(
                "Unknown enrollment request_id"
            )

        if result.get("accepted") is True:
            create_enrollment(
                person_id=pending["person_id"],
                reference_count=pending[
                    "reference_count"
                ],
            )

        # Request sudah selesai baik accepted maupun rejected.
        del self._pending[request_id]

        return {
            "request_id": request_id,
            "person_id": pending["person_id"],
            "accepted": bool(
                result.get("accepted")
            ),
            "reason": result.get("reason"),
            "collides_with": result.get(
                "collides_with"
            ),
            "collision_similarity": result.get(
                "collision_similarity"
            ),
            "images": result.get("images", []),
        }

    def is_pending(
        self,
        request_id: str,
    ) -> bool:
        return request_id in self._pending

    def handle_protocol_result(
        self,
        message: Dict[str, Any],
    ) -> Dict[str, Any]:
        validated = protocol_adapter.validate(
            message,
            expected_channel="control",
        )

        if validated.get("type") != "enroll_result":
            raise ValueError(
                "Expected enroll_result"
            )

        return self.handle_result(
            validated
        )

enrollment_service = EnrollmentService()