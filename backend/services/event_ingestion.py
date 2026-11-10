from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from backend.services.violation_service import violation_service
from backend.core.database import (
    get_protocol_events, get_track_history, mark_report_dirty, save_protocol_event,
)
from backend.core.database import get_employee_by_employee_id
from backend.services.break_policy import break_policy
from backend.core.state import system_state
from backend.services.free_time import free_time_ledger
from backend.services.protocol_adapter import protocol_adapter

logger = logging.getLogger(__name__)


def _timestamp(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def _local_dates(start_ts: float, end_ts: float) -> List[str]:
    """Semua tanggal lokal yang disentuh rentang [start_ts, end_ts]."""
    first = datetime.fromtimestamp(start_ts, break_policy.timezone).date()
    last = datetime.fromtimestamp(max(start_ts, end_ts), break_policy.timezone).date()
    dates = []
    while first <= last:
        dates.append(first.isoformat())
        first += timedelta(days=1)
    return dates


class EventIngestionService:
    def _resolve_identity(self, event: Dict[str, Any], outbox_id: str, seq: int,
                          event_time: float) -> Tuple[Dict[str, Any], List[str]]:
        """Atribusi mundur kelompok ANON ke karyawan (identity_source reid_retro).

        Mengembalikan (atribusi, tanggal lokal yang perlu dinilai ulang
        pelanggarannya; kosong bila karyawan tujuan tidak ada di master: perlu
        HR review). Atribusi disimpan pemanggil satu transaksi dengan event.
        Atribusi tidak dibatasi satu kamera karena kelompok ANON bisa lintas
        kamera; jendelanya mencakup semua interval yang dipindah.
        """
        anon_id = str(event.get("anon_id") or "")
        target = str(event.get("person_id") or "")
        moved = {str(item) for item in event.get("moved_intervals") or []}
        employee = get_employee_by_employee_id(target)

        starts: List[float] = []
        ends: List[float] = []
        if moved:
            # Lewat indeks (type, person_id): dulu memindai semua interval sepanjang sejarah.
            for row in get_protocol_events(event_type="presence.interval", person_id=anon_id):
                payload = row["payload"]
                if str(payload.get("interval_id")) in moved and payload.get("person_id") == anon_id:
                    starts.append(_timestamp(payload["start_at"]))
                    ends.append(_timestamp(payload["end_at"]))
        window_start = min(starts, default=event_time)
        window_end = max(ends, default=event_time)

        review_reason: Optional[str] = None if employee is not None else "missing_employee"
        record = {
            "event_outbox_id": outbox_id,
            "event_seq": seq,
            "original_person_id": anon_id,
            "employee_internal_id": employee.get("id") if employee else None,
            "attribution_source": "reid_retro",
            "attribution_confidence": 1.0 if employee is not None else 0.5,
            "needs_hr_review": review_reason is not None,
            "review_reason": review_reason,
            "track_uuid": None,
            "camera_id": None,
            "window_start": window_start,
            "window_end": window_end,
            "evidence": [{
                "type": "identity.resolved", "seq": seq, "reason": event.get("reason"),
                "trigger_track_uuid": event.get("trigger_track_uuid"),
                "track_uuids": list(event.get("track_uuids") or []),
                "moved_intervals": sorted(moved),
            }],
        }
        if employee is None:
            logger.warning("identity.resolved %s -> %s: karyawan tidak ada di master, perlu HR review",
                           anon_id, target)
            return record, []
        return record, _local_dates(window_start, max(window_end, event_time))

    def _identity_changed(self, event: Dict[str, Any], outbox_id: str, seq: int,
                          event_time: float) -> Tuple[Dict[str, Any], List[str]]:
        """Atribusi track.identity_changed dan tanggal laporan yang perlu ditandai."""
        target = event.get("to_person_id")
        employee = get_employee_by_employee_id(str(target or ""))
        track_uuid = str(event.get("track_uuid") or "")
        history: List[Dict[str, Any]] = []
        if track_uuid:
            # Dihitung SEBELUM event disimpan (atribusi ikut transaksinya), jadi
            # event ini sendiri ditambahkan seperti dulu ia terbaca dari DB.
            history = [
                item for item in get_track_history(track_uuid, event_time)
                if not (item["type"] == event.get("type") and item["payload"].get("seq") == seq)
            ]
            history.append({"timestamp": event_time, "type": event.get("type"), "payload": event})
        cameras = {item["payload"].get("camera_id") for item in history if item["payload"].get("camera_id")}
        previous = event.get("from_person_id")
        conflicting = previous not in (None, "", target)
        ambiguous_camera = len(cameras) > 1
        review_reason = None
        if employee is None:
            review_reason = "missing_employee"
        elif conflicting:
            review_reason = "conflicting_identity"
        elif ambiguous_camera:
            review_reason = "ambiguous_reid"
        elif not history:
            review_reason = "insufficient_evidence"
        needs_review = review_reason is not None
        window_start = min((item["timestamp"] for item in history), default=event_time)
        record = {
            "event_outbox_id": outbox_id,
            "event_seq": seq,
            "original_person_id": event.get("from_person_id"),
            "employee_internal_id": employee.get("id") if employee else None,
            "attribution_source": "identity_changed",
            "attribution_confidence": 1.0 if not needs_review else 0.5,
            "needs_hr_review": needs_review,
            "review_reason": review_reason,
            "track_uuid": track_uuid or None,
            "camera_id": next(iter(cameras)) if len(cameras) == 1 else event.get("camera_id"),
            "window_start": window_start,
            "window_end": event_time,
            "evidence": [
                {"type": item["type"], "timestamp": item["timestamp"]}
                for item in history
            ] + [{"type": "track.identity_changed", "seq": seq}],
        }
        dates = []
        if employee is not None:
            dates.append(datetime.fromtimestamp(window_start, break_policy.timezone).date().isoformat())
        return record, dates

    def ingest(self, message: Dict[str, Any], outbox_id: str = "") -> bool:
        validated = protocol_adapter.validate(message, expected_channel="events")

        seq = validated.get("seq")
        if not isinstance(seq, int):
            raise ValueError("Protocol event must contain integer seq")
        event_type = validated.get("type")
        if not isinstance(event_type, str):
            raise ValueError("Protocol event must contain type")

        event_time = validated.get("at")
        if not isinstance(event_time, str):
            event_time = validated.get("ts")
        if not isinstance(event_time, str):
            raise ValueError("Protocol event must contain at or ts")

        timestamp = _timestamp(event_time)
        attribution: Optional[Dict[str, Any]] = None
        dirty_dates: List[str] = []
        resolved_dates: List[str] = []
        if event_type == "track.identity_changed":
            attribution, dirty_dates = self._identity_changed(validated, outbox_id, seq, timestamp)
        elif event_type == "identity.resolved":
            attribution, resolved_dates = self._resolve_identity(validated, outbox_id, seq, timestamp)
            dirty_dates = resolved_dates

        # Satu transaksi: event, checkpoint seq, dan atribusinya. Galat DB di sini
        # tidak meninggalkan event tanpa atribusi; engine_client tidak meng-ACK-nya
        # sehingga engine memutar ulang.
        inserted = save_protocol_event(
            timestamp=timestamp,
            event_type=event_type,
            payload=validated,
            seq=seq,
            outbox_id=outbox_id,
            attribution=attribution,
        )
        if inserted:
            local_date = datetime.fromtimestamp(timestamp, break_policy.timezone).date().isoformat()
            mark_report_dirty(local_date)
            for dirty_date in dirty_dates:
                mark_report_dirty(dirty_date)
            free_time_ledger.apply_event(validated)

            # Event sudah tersimpan dan sudah masuk ledger. Kegagalan menilai
            # pelanggaran (DB, notifikasi) tidak boleh membuat event itu
            # dicatat sebagai dead letter oleh engine_client, dan tidak boleh
            # melewatkan record_event di bawah.
            try:
                violation_service.evaluate_event(validated)
                # Waktu yang baru dipindah bisa melampaui jatah pada tanggal mana pun yang
                # disentuh interval itu; dedupe per orang+tanggal ada di save_violation.
                for local_date in resolved_dates:
                    violation_service.evaluate(
                        str(validated["person_id"]), local_date, now=timestamp
                    )
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Evaluasi pelanggaran gagal untuk %s seq=%s", event_type, seq
                )

            system_state.record_event(
                event_type,
                validated,
            )
        return inserted

event_ingestion_service = EventIngestionService()
