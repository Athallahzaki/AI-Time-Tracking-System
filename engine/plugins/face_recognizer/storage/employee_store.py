from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


class EmployeeStore:
    """JSON-based storage for employee profile records."""

    def __init__(self, directory: Union[str, Path] = "data/employees") -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _get_path(self, employee_id: str) -> Path:
        return self._dir / f"{employee_id}.json"

    def save(self, employee_id: str, name: str, active: bool = True, extra: Optional[Dict[str, Any]] = None) -> None:
        path = self._get_path(employee_id)
        data = {
            "employee_id": employee_id,
            "name": name,
            "active": active,
            "extra": extra or {},
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def get(self, employee_id: str) -> Optional[Dict[str, Any]]:
        path = self._get_path(employee_id)
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def list_all(self) -> List[Dict[str, Any]]:
        results = []
        for file in self._dir.glob("*.json"):
            try:
                with open(file, "r", encoding="utf-8") as f:
                    results.append(json.load(f))
            except Exception as e:
                logger.warning(f"Failed to read employee record {file}: {e}")
        return results

    def list_active(self) -> List[Dict[str, Any]]:
        return [emp for emp in self.list_all() if emp.get("active", True)]

    def set_active(self, employee_id: str, active: bool) -> bool:
        emp = self.get(employee_id)
        if emp is None:
            return False
        emp["active"] = active
        with open(self._get_path(employee_id), "w", encoding="utf-8") as f:
            json.dump(emp, f, indent=2)
        return True
