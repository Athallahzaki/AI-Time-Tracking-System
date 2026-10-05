from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional, Set

from backend.core.database import save_violation
from backend.services.break_policy import break_policy
from backend.services.free_time import free_time_ledger
from backend.services.notification_service import notification_service

def _timestamp(value: Any) -> Optional[float]:
    if not isinstance(value, str) or not value:
        return None

    try:
        return datetime.fromisoformat(
            value.replace("Z", "+00:00")
        ).timestamp()
    except ValueError:
        return None


class ViolationService:
    def evaluate(
        self,
        person_id: str,
        local_date: str,
        now: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        now = now if now is not None else datetime.now().timestamp()

        usage = free_time_ledger.usage(
            person_id=str(person_id),
            local_date=local_date,
            now=now,
        )

        if usage["status"] != "exceeded":
            return None

        payload = {
            "person_id": str(person_id),
            "date": local_date,
            "type": "free_time_exceeded",
            "status": usage["status"],
            "used_seconds": usage["used_seconds"],
            "allowance_seconds": usage["allowance_seconds"],
            "remaining_seconds": usage["remaining_seconds"],
        }

        created = save_violation(
            person_id=str(person_id),
            local_date=local_date,
            occurred_at=now,
            used_seconds=usage["used_seconds"],
            allowance_seconds=usage["allowance_seconds"],
            payload=payload,
        )

        payload["created"] = created
        
        if created:
            notification_service.create_violation_notification(
                {
                    **payload,
                    "occurred_at": now,
                }
            )

        return payload

    def evaluate_event(
        self,
        event: Dict[str, Any],
    ) -> list[Dict[str, Any]]:
        """
        Evaluate people affected by one durable engine event.

        Called only after the durable event has been persisted and applied
        to FreeTimeLedger.
        """

        people: Set[str] = set()

        person_id = event.get("person_id")
        if person_id is not None:
            people.add(str(person_id))

        # identity_changed may affect either identity.
        for key in ("to_person_id", "from_person_id"):
            value = event.get(key)
            if value is not None:
                people.add(str(value))

        # Snapshot may contain multiple identified people.
        for item in event.get("live") or []:
            if not isinstance(item, dict):
                continue

            value = item.get("person_id")
            if value is not None:
                people.add(str(value))

        if not people:
            return []

        event_time = (
            _timestamp(event.get("at"))
            or _timestamp(event.get("ts"))
        )

        if event_time is None:
            return []

        dates = {
            break_policy.local_date(event_time),
        }

        # A presence.interval may cross a local-date boundary.
        for field in ("start_at", "end_at"):
            timestamp = _timestamp(event.get(field))

            if timestamp is not None:
                dates.add(
                    break_policy.local_date(timestamp)
                )

        results: list[Dict[str, Any]] = []

        for current_person in people:
            for local_date in dates:
                result = self.evaluate(
                    person_id=current_person,
                    local_date=local_date,
                    now=event_time,
                )

                if result is not None:
                    results.append(result)

        return results


violation_service = ViolationService()