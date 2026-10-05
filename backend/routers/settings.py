from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.core.security import require_admin
from backend.schemas.settings import FreeTimePolicyUpdate
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
def get_policy():
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
        policy = policy_service.update_free_time(
            daily_free_time_allowance_minutes=(
                req.daily_free_time_allowance_minutes
            ),
            warning_remaining_minutes=(
                req.warning_remaining_minutes
            ),
        )
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
def get_email_status():
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