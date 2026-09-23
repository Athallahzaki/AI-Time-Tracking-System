from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, Optional
from uuid import uuid4

from backend.core.database import next_enrollment_version, upsert_enrollment
from backend.schemas.enrollment import EnrollmentRequest
from backend.schemas.protocol import EnrollMessage
from backend.services.protocol_adapter import protocol_adapter

logger = logging.getLogger(__name__)

# A request the engine never answers is reported as failed after this long,
# instead of staying "pending" in the UI forever.
PENDING_TIMEOUT_SECONDS = 120.0


class EnrollmentService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        self._results: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()

    def create_request(self, request: EnrollmentRequest) -> EnrollMessage:
        if not request.images:
            raise ValueError("At least one enrollment image is required")

        request_id = f"enroll_{uuid4().hex}"
        version = next_enrollment_version(request.person_id)
        message = EnrollMessage(
            type="enroll",
            v=1,
            request_id=request_id,
            person_id=request.person_id,
            enrollment_version=version,
            images=[{"id": image.id, "jpeg_b64": image.jpeg_b64} for image in request.images],
        )
        with self._lock:
            self._pending[request_id] = {
                "person_id": request.person_id,
                "reference_count": len(request.images),
                "enrollment_version": version,
                "created_at": time.time(),
            }
        return message

    def _finish(self, request_id: str, pending: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
        outcome = {
            "request_id": request_id,
            "person_id": pending["person_id"],
            "status": "accepted" if result.get("accepted") else "rejected",
            "accepted": bool(result.get("accepted")),
            "reason": result.get("reason"),
            "collides_with": result.get("collides_with"),
            "collision_similarity": result.get("collision_similarity"),
            "images": result.get("images", []),
            "finished_at": time.time(),
        }
        with self._lock:
            self._results[request_id] = outcome
            while len(self._results) > 500:
                self._results.popitem(last=False)
        return outcome

    def handle_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        if result.get("type") != "enroll_result":
            raise ValueError("Expected enroll_result")
        request_id = result.get("request_id")
        with self._lock:
            pending = self._pending.pop(request_id, None)
        if pending is None:
            raise ValueError("Unknown enrollment request_id")

        if result.get("accepted") is True:
            upsert_enrollment(
                person_id=pending["person_id"],
                reference_count=pending["reference_count"],
                enrollment_version=pending["enrollment_version"],
            )
        return self._finish(request_id, pending, result)

    def handle_protocol_result(self, message: Dict[str, Any]) -> Dict[str, Any]:
        validated = protocol_adapter.validate(message, expected_channel="control")
        return self.handle_result(validated)

    def handle_rejection_ack(self, message: Dict[str, Any]) -> None:
        """Older engines answer `enroll` with a plain ack(accepted=false).

        An ack carries no request_id, so the oldest pending request is the one
        it answers (the engine handles control messages in order).
        """
        with self._lock:
            if not self._pending:
                return
            request_id, pending = self._pending.popitem(last=False)
        self._finish(request_id, pending, {"accepted": False, "reason": message.get("reason")})

    def is_pending(self, request_id: str) -> bool:
        self._expire()
        with self._lock:
            return request_id in self._pending

    def status(self, request_id: str) -> Optional[Dict[str, Any]]:
        self._expire()
        with self._lock:
            if request_id in self._results:
                return dict(self._results[request_id])
            pending = self._pending.get(request_id)
        if pending is None:
            return None
        return {"request_id": request_id, "person_id": pending["person_id"], "status": "pending"}

    def _expire(self) -> None:
        now = time.time()
        with self._lock:
            expired = [
                (rid, p) for rid, p in self._pending.items()
                if now - p["created_at"] > PENDING_TIMEOUT_SECONDS
            ]
            for rid, _ in expired:
                self._pending.pop(rid, None)
        for rid, pending in expired:
            self._finish(rid, pending, {"accepted": False, "reason": "engine_timeout"})


enrollment_service = EnrollmentService()
