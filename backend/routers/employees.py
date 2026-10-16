"""Employee CRUD router.

Endpoints:
    GET    /api/employees              — list (optional ?status=active|inactive)
    POST   /api/employees              — create
    GET    /api/employees/{internal_id} — get one
    PATCH  /api/employees/{internal_id} — partial update
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional

from backend.core.database import (
    create_employee,
    get_employee_by_employee_id,
    get_employee_by_id,
    get_employees,
    update_employee,
)
from backend.core.security import employee_scope, require_admin, require_user
from backend.schemas.employee import (
    EmployeeCreateRequest,
    EmployeeUpdateRequest,
)

router = APIRouter(
    prefix="/api/employees",
    tags=["Employees"],
)


@router.get("")
def list_employees(
    status: Optional[str] = Query(
        default=None,
        description="Filter by status: active or inactive",
    ),
    _user=Depends(require_user),
):
    employees = get_employees(status_filter=status)
    own = employee_scope(_user)
    if own:
        employees = [employee for employee in employees if employee["employee_id"] == own]
    return {
        "status": "success",
        "count": len(employees),
        "employees": employees,
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
            email=req.email,
            status=req.status,
        )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"employee_id '{req.employee_id}' already exists",
        ) from exc

    return {
        "status": "success",
        "employee": emp,
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
        "employee": emp,
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
    email_arg = req.email  # could be str, None, or Ellipsis

    try:
        updated = update_employee(
            internal_id=internal_id,
            employee_id=req.employee_id,
            name=req.name,
            email=email_arg if email_arg is not ... else ...,
            status=req.status,
        )
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
        "employee": updated,
    }
