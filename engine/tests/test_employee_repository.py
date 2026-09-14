from pathlib import Path

import numpy as np

from engine.plugins.face_recognizer.storage.repository import EmployeeRepository


def _embedding(value: float) -> np.ndarray:
    vector = np.full(512, value, dtype=np.float32)
    norm = np.linalg.norm(vector)

    if norm == 0:
        raise ValueError("Test embedding must not be zero.")

    return vector / norm


def test_register_employee_and_load_active_references(tmp_path: Path):
    employees_dir = tmp_path / "employees"
    embeddings_dir = tmp_path / "embeddings"

    repository = EmployeeRepository(
        employees_dir=employees_dir,
        embeddings_dir=embeddings_dir,
        embedding_dimension=512,
    )

    embeddings = [
        _embedding(1.0),
        _embedding(2.0),
    ]

    repository.register_employee(
        employee_id="EMP001",
        name="Alice",
        embeddings=embeddings,
    )

    references = repository.load_active_references()

    assert "EMP001" in references
    assert len(references["EMP001"]) == 2
    assert references["EMP001"][0].shape == (512,)
    assert references["EMP001"][1].shape == (512,)


def test_set_active_invalidates_reference_cache(tmp_path: Path):
    repository = EmployeeRepository(
        employees_dir=tmp_path / "employees",
        embeddings_dir=tmp_path / "embeddings",
        embedding_dimension=512,
    )

    repository.register_employee(
        employee_id="EMP001",
        name="Alice",
        embeddings=[_embedding(1.0)],
        active=True,
    )

    references = repository.load_active_references()

    assert "EMP001" in references

    repository.set_active("EMP001", False)

    references = repository.load_active_references()

    assert "EMP001" not in references


def test_delete_employee_removes_metadata_and_embeddings(tmp_path: Path):
    employees_dir = tmp_path / "employees"
    embeddings_dir = tmp_path / "embeddings"

    repository = EmployeeRepository(
        employees_dir=employees_dir,
        embeddings_dir=embeddings_dir,
        embedding_dimension=512,
    )

    repository.register_employee(
        employee_id="EMP001",
        name="Alice",
        embeddings=[_embedding(1.0)],
    )

    assert (employees_dir / "EMP001.json").exists()
    assert (embeddings_dir / "EMP001.npy").exists()

    assert repository.delete_employee("EMP001") is True

    assert not (employees_dir / "EMP001.json").exists()
    assert not (embeddings_dir / "EMP001.npy").exists()
    assert repository.load_active_references() == {}


def test_delete_employee_returns_false_when_identity_does_not_exist(
    tmp_path: Path,
):
    repository = EmployeeRepository(
        employees_dir=tmp_path / "employees",
        embeddings_dir=tmp_path / "embeddings",
        embedding_dimension=512,
    )

    assert repository.delete_employee("UNKNOWN") is False

def test_register_employee_invalidates_reference_cache(tmp_path: Path):
    repository = EmployeeRepository(
        employees_dir=tmp_path / "employees",
        embeddings_dir=tmp_path / "embeddings",
        embedding_dimension=512,
    )

    repository.register_employee(
        employee_id="EMP001",
        name="Alice",
        embeddings=[_embedding(1.0)],
    )

    first_references = repository.load_active_references()
    assert set(first_references) == {"EMP001"}

    repository.register_employee(
        employee_id="EMP002",
        name="Bob",
        embeddings=[_embedding(2.0)],
    )

    second_references = repository.load_active_references()

    assert set(second_references) == {"EMP001", "EMP002"}