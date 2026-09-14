from __future__ import annotations

from typing import List

import numpy as np

from ..contracts.identity import (
    EnrollmentRequest,
    EnrollmentResult,
    Identity,
)
from ..contracts.interfaces import EnrollmentRepository
from ..pipeline.enrollment import EnrollmentService


class IdentityNotFoundError(Exception):
    """Raised when an identity does not exist."""


class IdentityService:
    """
    Public identity-management facade.

    Coordinates enrollment workflow and identity lifecycle operations
    without exposing storage or model implementation details.
    """

    def __init__(
        self,
        enrollment_service: EnrollmentService,
        repository: EnrollmentRepository,
    ) -> None:
        self._enrollment_service = enrollment_service
        self._repository = repository

    def enroll(
        self,
        request: EnrollmentRequest,
    ) -> EnrollmentResult:
        self._enrollment_service.enroll(
            employee_id=request.employee_id,
            name=request.name,
            images=request.images,
            active=request.active,
        )

        return EnrollmentResult(
            employee_id=request.employee_id,
            name=request.name,
            reference_count=len(request.images),
            active=request.active,
        )

    def get(self, employee_id: str) -> Identity:
        employee = self._repository.get_employee(employee_id)

        if employee is None:
            raise IdentityNotFoundError(
                f"Identity '{employee_id}' was not found."
            )

        return Identity(
            employee_id=str(employee["employee_id"]),
            name=str(employee["name"]),
            active=bool(employee.get("active", True)),
        )

    def list(self) -> List[Identity]:
        employees = self._repository.list_employees()

        return [
            Identity(
                employee_id=str(employee["employee_id"]),
                name=str(employee["name"]),
                active=bool(employee.get("active", True)),
            )
            for employee in employees
        ]

    def activate(self, employee_id: str) -> Identity:
        self._set_active(employee_id, True)
        return self.get(employee_id)

    def deactivate(self, employee_id: str) -> Identity:
        self._set_active(employee_id, False)
        return self.get(employee_id)

    def delete(self, employee_id: str) -> None:
        deleted = self._repository.delete_employee(employee_id)

        if not deleted:
            raise IdentityNotFoundError(
                f"Identity '{employee_id}' was not found."
            )

    def _set_active(
        self,
        employee_id: str,
        active: bool,
    ) -> None:
        employee = self._repository.get_employee(employee_id)

        if employee is None:
            raise IdentityNotFoundError(
                f"Identity '{employee_id}' was not found."
            )

        self._repository.set_active(
            employee_id=employee_id,
            active=active,
        )