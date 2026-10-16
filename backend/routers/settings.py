from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.core.security import require_admin, require_user
from backend.core.database import get_app_setting, set_app_setting
from backend.schemas.settings import (
    CameraScheduleSettings, FreeTimePolicyUpdate, HRRecipientSettings,
    ReportScheduleSettings,
)
from backend.services.policy_service import policy_service
from backend.services.email_service import (
    EmailConfigurationError,
    EmailDeliveryError,
    email_service,
)


router = APIRouter(
    prefix="/api/settings",
    tags=["Settings"],
)


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
