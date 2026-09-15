from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional, Union
import numpy as np

from .employee_store import EmployeeStore
from .embedding_store import EmbeddingStore

logger = logging.getLogger(__name__)


class EmployeeRepository:
    """
    Coordinates employee metadata and reference embeddings.
    Serves as the high-level identity provider for FaceMatcher.
    """

    def __init__(
        self,
        employees_dir: Union[str, Path] = "data/employees",
        embeddings_dir: Union[str, Path] = "data/embeddings",
        embedding_dimension: int = 512,
    ) -> None:
        self._employee_store = EmployeeStore(employees_dir)
        self._embedding_store = EmbeddingStore(embeddings_dir, embedding_dimension=embedding_dimension)
        self._cached_references: Optional[Dict[str, List[np.ndarray]]] = None

    def load_active_references(self, force_reload: bool = False) -> Dict[str, List[np.ndarray]]:
        """
        Loads embeddings belonging to active registered employees.
        Caches in memory for low-latency matching.
        """
        if self._cached_references is not None and not force_reload:
            return self._cached_references

        references: Dict[str, List[np.ndarray]] = {}
        active_employees = self._employee_store.list_active()

        for emp in active_employees:
            emp_id = emp["employee_id"]
            if not self._embedding_store.exists(emp_id):
                continue

            embs = self._embedding_store.load(emp_id)
            if embs:
                references[emp_id] = embs

        self._cached_references = references
        logger.info(f"Loaded {len(references)} active employee references into memory.")
        return references

    def register_employee(
        self,
        employee_id: str,
        name: str,
        embeddings: List[np.ndarray],
        active: bool = True,
    ) -> None:
        """Enrolls or updates an employee and invalidates the in-memory cache."""
        self._employee_store.save(
            employee_id=employee_id,
            name=name,
            active=active,
        )
        self._embedding_store.save(
            employee_id=employee_id,
            embeddings=embeddings,
        )
        self._cached_references = None

    def set_active(self, employee_id: str, active: bool) -> None:
        self._employee_store.set_active(employee_id, active)
        self._cached_references = None

    def get_employee(self, employee_id: str) -> Optional[Dict[str, object]]:
        return self._employee_store.get(employee_id)

    def list_employees(self) -> List[Dict[str, object]]:
        return self._employee_store.list_all()

    def reload(self) -> None:
        self.load_active_references(force_reload=True)

    def delete_employee(self, employee_id: str) -> bool:
        deleted_employee = self._employee_store.delete(employee_id)
        deleted_embedding = self._embedding_store.delete(employee_id)

        if deleted_employee or deleted_embedding:
            self._cached_references = None
            return True

        return False