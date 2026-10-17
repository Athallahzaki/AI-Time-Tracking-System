from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from datetime import datetime, timedelta

from backend.core.security import require_admin, require_user
from backend.core.database import (
    add_settings_audit, get_app_setting, get_settings_audit, set_app_setting,
)
from backend.schemas.settings import (
    CameraScheduleSettings, FreeTimePolicyUpdate, HRRecipientSettings,
    ReportScheduleSettings,
    WeeklySettingsRequest, EmailRecapSettings,
)
from backend.services.policy_service import policy_service
from backend.services.break_policy import break_policy
from backend.services.email_service import (
    EmailConfigurationError,
    EmailDeliveryError,
    email_service,
)


router = APIRouter(
    prefix="/api/settings",
    tags=["Settings"],
)

DAY_NAMES = {"mon": "monday", "tue": "tuesday", "wed": "wednesday", "thu": "thursday",
             "fri": "friday", "sat": "saturday", "sun": "sunday"}


def _validate_days(days, engine=False):
    if set(days) != set(DAY_NAMES):
        raise HTTPException(status_code=400, detail="days must contain mon..sun")
    for day, value in days.items():
        ranges = [value] if engine else value
        previous_end = None
        normalized = []
        for item in ranges:
            if engine and not item.get("enabled", False):
                continue
            start, end = item.get("start", ""), item.get("end", "")
            def minutes(clock):
                parts = clock.split(":")
                if len(parts) != 2 or not all(part.isdigit() for part in parts):
                    return None
                hour, minute = map(int, parts)
                return hour * 60 + minute if 0 <= hour <= 23 and 0 <= minute <= 59 else None
            start_minute, end_minute = minutes(start), minutes(end)
            if start_minute is None or end_minute is None or start_minute >= end_minute:
                raise HTTPException(status_code=400, detail=f"invalid time range for {day}")
            normalized.append((start_minute, end_minute))
        for start_minute, end_minute in sorted(normalized):
            if previous_end is not None and start_minute < previous_end:
                raise HTTPException(status_code=400, detail=f"overlapping time range for {day}")
            previous_end = end_minute


def _break_payload():
    today = datetime.now(break_policy.timezone).date()
    current = get_app_setting("break_hours_current")
    if not current:
        policy = policy_service.get().get("official_breaks", {})
        reverse = {name: key for key, name in DAY_NAMES.items()}
        days = {key: policy.get(name, []) for name, key in reverse.items()}
        current = {"effective_from": today.isoformat(), "days": days}
        set_app_setting("break_hours_current", current)
    pending = get_app_setting("break_hours_pending")
    if pending and pending["effective_from"] <= today.isoformat():
        current = pending
        official = {DAY_NAMES[key]: value for key, value in pending["days"].items()}
        policy_service.update({"official_breaks": official})
        set_app_setting("break_hours_current", current)
        set_app_setting("break_hours_pending", None)
        pending = None
    return {"current": current, "pending": pending}


@router.get("/policy")
def get_policy(_user=Depends(require_user)):
    try:
        return {
            "status": "success",
            "policy": policy_service.get(),
        }
    except (OSError, ValueError) as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc


@router.put(
    "/policy",
    dependencies=[Depends(require_admin)],
)
def update_policy(req: FreeTimePolicyUpdate):
    try:
        policy = policy_service.update(req.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail="Failed to save policy configuration",
        ) from exc

    return {
        "status": "success",
        "policy": policy,
    }

@router.get("/email")
def get_email_status(_user=Depends(require_user)):
    return {
        "status": "success",
        "email": email_service.status(),
    }


@router.post(
    "/email/test",
    dependencies=[Depends(require_admin)],
)
def test_email():
    try:
        email_service.send_test_email()

    except EmailConfigurationError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except EmailDeliveryError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"SMTP delivery failed: {exc}",
        ) from exc

    return {
        "status": "success",
        "message": "Test email sent",
        "recipients": email_service.status()[
            "recipients"
        ],
    }


@router.get("/hr-recipients")
def get_hr_recipients(_admin=Depends(require_admin)):
    return {"status": "success", "settings": get_app_setting("hr_recipients", {})}


@router.put("/hr-recipients")
def put_hr_recipients(req: HRRecipientSettings, _admin=Depends(require_admin)):
    value = req.model_dump()
    set_app_setting("hr_recipients", value)
    return {"status": "success", "settings": value}


@router.get("/report-schedule")
def get_report_schedule(_admin=Depends(require_admin)):
    return {"status": "success", "settings": get_app_setting("report_schedule", {})}


@router.put("/report-schedule")
def put_report_schedule(req: ReportScheduleSettings, _admin=Depends(require_admin)):
    if req.enabled and not req.recipients:
        raise HTTPException(status_code=400, detail="enabled report schedule needs recipients")
    value = req.model_dump()
    set_app_setting("report_schedule", value)
    return {"status": "success", "settings": value}


@router.get("/camera-schedule")
def get_camera_schedule(_admin=Depends(require_admin)):
    return {"status": "success", "settings": get_app_setting("camera_schedule", {})}


@router.put("/camera-schedule")
def put_camera_schedule(req: CameraScheduleSettings, _admin=Depends(require_admin)):
    value = req.model_dump()
    for camera_id, weekdays in value["cameras"].items():
        from backend.core.config import settings
        if camera_id not in settings.cameras:
            raise HTTPException(status_code=400, detail=f"unknown camera: {camera_id}")
        for day, windows in weekdays.items():
            if day.lower() not in {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}:
                raise HTTPException(status_code=400, detail=f"unknown weekday: {day}")
            ordered = sorted((item["start"], item["end"]) for item in windows)
            for index, (start, end) in enumerate(ordered):
                if start >= end:
                    raise HTTPException(status_code=400, detail=f"invalid schedule window: {start}-{end}")
                if index and ordered[index - 1][1] > start:
                    raise HTTPException(status_code=400, detail=f"overlapping schedule for {camera_id}/{day}")
    set_app_setting("camera_schedule", value)
    return {"status": "success", "settings": value}


@router.get("/break-hours")
def get_break_hours(_user=Depends(require_user)):
    return _break_payload()


@router.put("/break-hours")
def put_break_hours(req: WeeklySettingsRequest, admin=Depends(require_admin)):
    _validate_days(req.days)
    before = _break_payload()
    pending = {
        "effective_from": (datetime.now(break_policy.timezone).date() + timedelta(days=1)).isoformat(),
        "days": req.days,
    }
    set_app_setting("break_hours_pending", pending)
    add_settings_audit(admin["username"], "Jam istirahat resmi", before, pending)
    return {"current": before["current"], "pending": pending}


@router.delete("/break-hours/pending")
def cancel_break_hours(admin=Depends(require_admin)):
    before = _break_payload()
    set_app_setting("break_hours_pending", None)
    add_settings_audit(admin["username"], "Jam istirahat resmi (batal)", before.get("pending"), None)
    return {"current": before["current"], "pending": None}


def _engine_schedule_payload():
    value = get_app_setting("engine_schedule") or {
        "days": {key: {"enabled": key not in {"sat", "sun"}, "start": "07:00", "end": "18:00"}
                 for key in DAY_NAMES}
    }
    from backend.services.camera_state import engine_schedule_status
    return {**value, **engine_schedule_status(value)}


@router.get("/engine-schedule")
def get_engine_schedule(_user=Depends(require_user)):
    return _engine_schedule_payload()


@router.put("/engine-schedule")
def put_engine_schedule(req: WeeklySettingsRequest, admin=Depends(require_admin)):
    _validate_days(req.days, engine=True)
    before = get_app_setting("engine_schedule")
    value = {"days": req.days}
    set_app_setting("engine_schedule", value)
    add_settings_audit(admin["username"], "Jadwal operasional engine", before, value)
    return _engine_schedule_payload()


@router.get("/email/recap")
def get_email_recap(_admin=Depends(require_admin)):
    value = get_app_setting("email_recap", {"recap_recipients": [], "recap_send_time": "18:00"})
    return {**value, "default_from_env": email_service.status()["recipients"]}


@router.put("/email/recap")
def put_email_recap(req: EmailRecapSettings, admin=Depends(require_admin)):
    before = get_app_setting("email_recap", {})
    value = req.model_dump()
    set_app_setting("email_recap", value)
    schedule = get_app_setting("report_schedule", {}) or {}
    schedule.update({"enabled": bool(value["recap_recipients"]), "timezone": "Asia/Jakarta",
                     "send_time": value["recap_send_time"], "recipients": value["recap_recipients"],
                     "cc": schedule.get("cc", [])})
    set_app_setting("report_schedule", schedule)
    add_settings_audit(admin["username"], "Email rekap harian", before, value)
    return {**value, "default_from_env": email_service.status()["recipients"]}


@router.get("/audit")
def settings_audit(limit: int = Query(50, ge=1, le=500), _admin=Depends(require_admin)):
    return {"items": get_settings_audit(limit)}
