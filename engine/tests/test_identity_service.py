import numpy as np
import pytest

from engine.plugins.face_recognizer.contracts.identity import (
    EnrollmentRequest,
    Identity,
)
from engine.plugins.face_recognizer.pipeline.enrollment import (
    EnrollmentService,
)
from engine.plugins.face_recognizer.service.identity_service import (
    IdentityNotFoundError,
    IdentityService,
)


class FakeEnrollmentService:
    def __init__(self):
        self.calls = []

    def enroll(
        self,
        employee_id,
        name,
        images,
        active=True,
    ):
        self.calls.append(
            {
                "employee_id": employee_id,
                "name": name,
                "images": images,
                "active": active,
            }
        )


class FakeRepository:
    def __init__(self):
        self.employees = {}

    def register_employee(
        self,
        employee_id,
        name,
        embeddings,
        active=True,
    ):
        self.employees[employee_id] = {
            "employee_id": employee_id,
            "name": name,
            "active": active,
        }

    def set_active(self, employee_id, active):
        if employee_id not in self.employees:
            raise KeyError(employee_id)

        self.employees[employee_id]["active"] = active

    def delete_employee(self, employee_id):
        if employee_id not in self.employees:
            return False

        del self.employees[employee_id]
        return True

    def get_employee(self, employee_id):
        return self.employees.get(employee_id)

    def list_employees(self):
        return list(self.employees.values())


def make_service():
    enrollment_service = FakeEnrollmentService()
    repository = FakeRepository()

    service = IdentityService(
        enrollment_service=enrollment_service,
        repository=repository,
    )

    return service, enrollment_service, repository


def test_enroll_returns_result():
    service, enrollment_service, _ = make_service()

    images = [
        np.zeros((112, 112, 3), dtype=np.uint8),
        np.ones((112, 112, 3), dtype=np.uint8),
    ]

    request = EnrollmentRequest(
        employee_id="EMP001",
        name="Alice",
        images=images,
    )

    result = service.enroll(request)

    assert result.employee_id == "EMP001"
    assert result.name == "Alice"
    assert result.reference_count == 2
    assert result.active is True

    assert len(enrollment_service.calls) == 1
    assert enrollment_service.calls[0]["employee_id"] == "EMP001"


def test_get_returns_identity():
    service, _, repository = make_service()

    repository.employees["EMP001"] = {
        "employee_id": "EMP001",
        "name": "Alice",
        "active": True,
    }

    identity = service.get("EMP001")

    assert isinstance(identity, Identity)
    assert identity.employee_id == "EMP001"
    assert identity.name == "Alice"
    assert identity.active is True


def test_get_raises_for_unknown_identity():
    service, _, _ = make_service()

    with pytest.raises(IdentityNotFoundError):
        service.get("UNKNOWN")


def test_list_returns_identity_dtos():
    service, _, repository = make_service()

    repository.employees = {
        "EMP001": {
            "employee_id": "EMP001",
            "name": "Alice",
            "active": True,
        },
        "EMP002": {
            "employee_id": "EMP002",
            "name": "Bob",
            "active": False,
        },
    }

    identities = service.list()

    assert len(identities) == 2
    assert all(isinstance(item, Identity) for item in identities)

    assert identities[0].employee_id == "EMP001"
    assert identities[0].active is True

    assert identities[1].employee_id == "EMP002"
    assert identities[1].active is False


def test_activate_identity():
    service, _, repository = make_service()

    repository.employees["EMP001"] = {
        "employee_id": "EMP001",
        "name": "Alice",
        "active": False,
    }

    result = service.activate("EMP001")

    assert result.active is True


def test_deactivate_identity():
    service, _, repository = make_service()

    repository.employees["EMP001"] = {
        "employee_id": "EMP001",
        "name": "Alice",
        "active": True,
    }

    result = service.deactivate("EMP001")

    assert result.active is False


def test_delete_identity():
    service, _, repository = make_service()

    repository.employees["EMP001"] = {
        "employee_id": "EMP001",
        "name": "Alice",
        "active": True,
    }

    service.delete("EMP001")

    assert "EMP001" not in repository.employees


def test_delete_unknown_identity_raises():
    service, _, _ = make_service()

    with pytest.raises(IdentityNotFoundError):
        service.delete("UNKNOWN")