from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import Any

import yaml

from backend.services.free_time import free_time_ledger
from backend.core.config import settings
from backend.services.break_policy import break_policy, load_break_policy


class PolicyService:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = Lock()

    def get(self) -> dict[str, Any]:
        policy = load_break_policy(self.path)

        return {
            "daily_free_time_allowance_minutes": policy.daily_allowance_minutes,
            "warning_remaining_minutes": policy.warning_remaining_minutes,
            "qualification_seconds": policy.qualification_seconds,
            "official_breaks": [
                {
                    "start": self._minutes_to_hhmm(start),
                    "end": self._minutes_to_hhmm(end),
                }
                for start, end in policy.official_breaks
            ],
            "visit_merge_gap_seconds": policy.visit_merge_gap_seconds,
            "open_presence_stale_seconds": policy.open_presence_stale_seconds,
            "timezone": policy.timezone_name,
        }

    def update_free_time(
        self,
        daily_free_time_allowance_minutes: float,
        warning_remaining_minutes: float,
    ) -> dict[str, Any]:
        if warning_remaining_minutes > daily_free_time_allowance_minutes:
            raise ValueError(
                "warning_remaining_minutes cannot exceed "
                "daily_free_time_allowance_minutes"
            )

        with self._lock:
            data = self._read_yaml()

            data["daily_free_time_allowance_minutes"] = float(
                daily_free_time_allowance_minutes
            )
            data["warning_remaining_minutes"] = float(
                warning_remaining_minutes
            )

            # Validate the complete resulting policy before replacing the file.
            temp_path = self.path.with_suffix(self.path.suffix + ".tmp")

            try:
                temp_path.write_text(
                    yaml.safe_dump(
                        data,
                        sort_keys=False,
                        allow_unicode=True,
                    ),
                    encoding="utf-8",
                )

                new_policy = load_break_policy(temp_path)

                temp_path.replace(self.path)
            finally:
                if temp_path.exists():
                    temp_path.unlink()

            # Keep the same global object because FreeTimeLedger and other
            # services already hold a reference to it.
            break_policy.timezone_name = new_policy.timezone_name
            break_policy.qualification_seconds = new_policy.qualification_seconds
            break_policy.daily_allowance_minutes = new_policy.daily_allowance_minutes
            break_policy.warning_remaining_minutes = (
                new_policy.warning_remaining_minutes
            )
            break_policy.official_breaks = list(new_policy.official_breaks)
            break_policy.visit_merge_gap_seconds = (
                new_policy.visit_merge_gap_seconds
            )
            break_policy.open_presence_stale_seconds = (
                new_policy.open_presence_stale_seconds
            )
            break_policy.__post_init__()
            free_time_ledger.invalidate()
            
        return self.get()

    def _read_yaml(self) -> dict[str, Any]:
        if not self.path.exists():
            raise FileNotFoundError(
                f"Policy config not found: {self.path}"
            )

        data = yaml.safe_load(
            self.path.read_text(encoding="utf-8")
        ) or {}

        if not isinstance(data, dict):
            raise ValueError("Policy config must be a YAML mapping")

        return data

    @staticmethod
    def _minutes_to_hhmm(minutes: int) -> str:
        hour = minutes // 60
        minute = minutes % 60
        return f"{hour:02d}:{minute:02d}"


policy_service = PolicyService(settings.policy_yaml_path)