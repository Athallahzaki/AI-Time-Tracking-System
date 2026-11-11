"""Employee CRUD router.

Endpoints:
    GET    /api/employees              — list (optional ?status=active|inactive)
    POST   /api/employees              — create
    GET    /api/employees/{internal_id} — get one
    PATCH  /api/employees/{internal_id} — partial update
"""

from __future__ import annotations

import sqlite3
import secrets

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional

from backend.core.config import settings
from backend.core.database import (
    add_exemption,
    create_employee,
    get_exemptions,
    revoke_exemption,
    get_employee_by_employee_id,
    get_employee_by_id,
    get_employees,
    get_enrollments,
    get_users,
    update_employee,
)
from backend.services.auth_service import auth_service
from backend.core.security import employee_scope, require_admin, require_user
from backend.schemas.employee import (
    EmployeeCreateRequest,
    EmployeeUpdateRequest,
    ExemptionCreateRequest,
)
from backend.services.free_time import free_time_ledger

router = APIRouter(
    prefix="/api/employees",
    tags=["Employees"],
)


def _public(employee):
    enrollments = {item["person_id"]: item for item in get_enrollments()}
    users = get_users()
    enrollment = enrollments.get(str(employee["employee_id"]))
    return {
        **employee,
        "uid": str(employee["id"]),
        "active": employee["status"] == "active",
        "enrolled_refs": int(enrollment["reference_count"]) if enrollment else 0,
        "has_account": any(item.get("employee_internal_id") == employee["id"] for item in users),
    }


@router.get("")
def list_employees(
    status: Optional[str] = Query(
        default=None,
        description="Filter by status: active or inactive",
    ),
    q: Optional[str] = None,
    division: Optional[str] = None,
    _user=Depends(require_user),
):
    if status == "all":
        status = None
    employees = get_employees(status_filter=status)
    own = employee_scope(_user)
    if own:
        employees = [employee for employee in employees if employee["employee_id"] == own]
    if division:
        employees = [employee for employee in employees if employee.get("division") == division]
    if q:
        needle = q.casefold()
        employees = [employee for employee in employees if needle in " ".join(
            str(employee.get(key) or "") for key in ("employee_id", "name", "division", "email")
        ).casefold()]
    items = [_public(employee) for employee in employees]
    return {
        "status": "success",
        "count": len(items),
        "employees": items,
        "items": items,
    }


@router.post("", status_code=201)
def create_new_employee(
    req: EmployeeCreateRequest,
    _user=Depends(require_admin),
):
    # Duplicate check with friendly message.
    existing = get_employee_by_employee_id(req.employee_id)
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=f"employee_id '{req.employee_id}' already exists",
        )

    try:
        emp = create_employee(
            employee_id=req.employee_id,
            name=req.name,
            division=req.division,
            email=req.email,
            status=req.status,
            allowance_minutes=req.allowance_minutes,
        )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"employee_id '{req.employee_id}' already exists",
        ) from exc

    return {
        "status": "success",
        "employee": _public(emp),
    }


@router.get("/{internal_id}")
def get_one_employee(
    internal_id: int,
    _user=Depends(require_user),
):
    emp = get_employee_by_id(internal_id)
    if emp is None:
        raise HTTPException(
            status_code=404,
            detail="Employee not found",
        )
    own = employee_scope(_user)
    if own and emp["employee_id"] != own:
        raise HTTPException(status_code=403, detail="Viewer cannot access another employee")
    return {
        "status": "success",
        "employee": _public(emp),
    }


@router.patch("/{internal_id}")
def patch_employee(
    internal_id: int,
    req: EmployeeUpdateRequest,
    _user=Depends(require_admin),
):
    # Verify employee exists first.
    existing = get_employee_by_id(internal_id)
    if existing is None:
        raise HTTPException(
            status_code=404,
            detail="Employee not found",
        )

    # If changing employee_id, check for duplicates.
    if req.employee_id is not None and req.employee_id != existing["employee_id"]:
        dup = get_employee_by_employee_id(req.employee_id)
        if dup is not None:
            raise HTTPException(
                status_code=409,
                detail=f"employee_id '{req.employee_id}' already exists",
            )

    # Determine email value: Pydantic uses ... as default sentinel.
    # If the field was not provided in the request body, it stays as ... (Ellipsis).
    # If it was explicitly set to null, it becomes None.
    email_arg = req.email if "email" in req.model_fields_set else ...

    try:
        updated = update_employee(
            internal_id=internal_id,
            employee_id=req.employee_id,
            name=req.name,
            division=req.division if "division" in req.model_fields_set else ...,
            email=email_arg if email_arg is not ... else ...,
            status=req.status,
            allowance_minutes=req.allowance_minutes if "allowance_minutes" in req.model_fields_set else ...,
        )
        free_time_ledger.invalidate()  # jatah baru berlaku tanpa menunggu event berikutnya
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc
    except sqlite3.IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"employee_id '{req.employee_id}' already exists",
        ) from exc

    return {
        "status": "success",
        "employee": _public(updated),
    }


def _employee_or_404(internal_id: int):
    employee = get_employee_by_id(internal_id)
    if employee is None:
        raise HTTPException(status_code=404, detail="Employee not found")
    return employee


@router.get("/{internal_id}/exemptions")
def list_exemptions(internal_id: int, _admin=Depends(require_admin)):
    """Pengecualian lokasi karyawan ini (JAT-07), termasuk yang sudah dicabut."""
    employee = _employee_or_404(internal_id)
    return {"status": "success", "exemptions": get_exemptions(str(employee["employee_id"]))}


@router.post("/{internal_id}/exemptions", status_code=201)
def create_exemption(internal_id: int, req: ExemptionCreateRequest, admin=Depends(require_admin)):
    employee = _employee_or_404(internal_id)
    person_id = str(employee["employee_id"])
    if req.camera_id not in settings.cameras:
        raise HTTPException(status_code=404, detail=f"Camera '{req.camera_id}' not found")
    if any(item["camera_id"] == req.camera_id for item in get_exemptions(person_id, include_revoked=False)):
        raise HTTPException(status_code=409, detail="Pengecualian untuk lokasi ini sudah aktif")
    exemption = add_exemption(person_id, req.camera_id, created_by=admin["username"], reason=req.reason)
    free_time_ledger.invalidate()
    return {"status": "success", "exemption": exemption}


@router.delete("/{internal_id}/exemptions/{exemption_id}")
def delete_exemption(internal_id: int, exemption_id: int, admin=Depends(require_admin)):
    """Mencabut, bukan menghapus: kunjungan selama pengecualian aktif tetap tidak ditagih."""
    employee = _employee_or_404(internal_id)
    if not revoke_exemption(exemption_id, revoked_by=admin["username"], person_id=str(employee["employee_id"])):
        raise HTTPException(status_code=404, detail="Pengecualian tidak ditemukan atau sudah dicabut")
    free_time_ledger.invalidate()
    return {"status": "success"}


@router.post("/{internal_id}/activate")
def activate_employee(internal_id: int, _admin=Depends(require_admin)):
    employee = update_employee(internal_id, status="active")
    if employee is None:
        raise HTTPException(status_code=404, detail="Employee not found")
    return {"employee": _public(employee)}


@router.post("/{internal_id}/deactivate")
def deactivate_employee(internal_id: int, _admin=Depends(require_admin)):
    employee = update_employee(internal_id, status="inactive")
    if employee is None:
        raise HTTPException(status_code=404, detail="Employee not found")
    from backend.core.database import disable_employee_access
    disable_employee_access(internal_id, str(employee["employee_id"]))
    return {"employee": _public(employee)}


@router.post("/{internal_id}/account", status_code=201)
def create_employee_account(internal_id: int, _admin=Depends(require_admin)):
    employee = get_employee_by_id(internal_id)
    if employee is None:
        raise HTTPException(status_code=404, detail="Employee not found")
    if employee["status"] != "active":
        raise HTTPException(status_code=409, detail="Inactive employee cannot receive an account")
    if any(user.get("employee_internal_id") == internal_id for user in get_users()):
        raise HTTPException(status_code=409, detail="Employee already has an account")
    password = secrets.token_urlsafe(10)
    auth_service.create_user(
        username=str(employee["employee_id"]), password=password, role="viewer",
        employee_internal_id=internal_id, must_change_password=True,
    )
    return {"username": employee["employee_id"], "temporary_password": password}
