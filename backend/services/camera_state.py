"""Satu sumber kebenaran untuk state kamera yang DIINGINKAN.

Sebelumnya ada dua: `cameras.yaml` (dipakai saat reconnect) dan `_overrides`
di memori router (dipakai saat operator menekan start/stop). Setelah engine
reconnect, perubahan operator dibatalkan diam-diam; setelah backend restart,
hilang. Sekarang override operator disimpan di SQLite dan kedua jalur memanggil
fungsi yang sama.
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Any, Dict, List

from backend.core.config import CameraConfig, settings
from backend.core.database import get_app_setting, get_camera_overrides


def _schedule_allows(camera_id: str, now: datetime | None = None) -> bool:
    global_schedule = get_app_setting("engine_schedule", {}) or {}
    if global_schedule.get("days"):
        if not engine_schedule_status(global_schedule, now).get("now_active"):
            return False
    schedule = get_app_setting("camera_schedule", {}) or {}
    camera_schedule = (schedule.get("cameras") or {}).get(camera_id)
    if camera_schedule is None:
        return True
    zone = ZoneInfo(schedule.get("timezone", "Asia/Jakarta"))
    local_now = (now or datetime.now(timezone.utc)).astimezone(zone)
    windows = camera_schedule.get(local_now.strftime("%A").lower(), [])
    clock = local_now.strftime("%H:%M")
    return any(item["start"] <= clock < item["end"] for item in windows)


def engine_schedule_status(schedule: Dict[str, Any], now: datetime | None = None) -> Dict[str, Any]:
    zone = ZoneInfo("Asia/Jakarta")
    local_now = (now or datetime.now(timezone.utc)).astimezone(zone)
    keys = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    rule = (schedule.get("days") or {}).get(keys[local_now.weekday()], {})
    if not rule.get("enabled"):
        return {"now_active": False, "next_change_at": None}
    clock = local_now.strftime("%H:%M")
    start, end = rule.get("start", "00:00"), rule.get("end", "00:00")
    if clock < start:
        return {"now_active": False, "next_change_at": start}
    if clock < end:
        return {"now_active": True, "next_change_at": end}
    return {"now_active": False, "next_change_at": None}


def effective_cameras() -> List[Dict[str, Any]]:
    overrides = get_camera_overrides()
    result = []
    for camera_id, config in settings.cameras.items():
        override = overrides.get(camera_id, {})
        source_uri = override.get("source_uri", config.source_uri)
        if not source_allowed(config, source_uri):
            # The allow-list shrank since the override was stored.
            source_uri = config.source_uri
        result.append({
            "config": config,
            "camera_id": camera_id,
            "source_uri": source_uri,
            "enabled": bool(override.get("enabled", config.enabled_by_default)) and _schedule_allows(camera_id),
        })
    return result


def source_allowed(config: CameraConfig, uri: str) -> bool:
    return uri == config.source_uri or uri in config.allowed_sources


def set_cameras_message() -> Dict[str, Any]:
    cameras = []
    for item in effective_cameras():
        entry: Dict[str, Any] = {
            "camera_id": item["camera_id"],
            "uri": item["source_uri"],
            "enabled": item["enabled"],
        }
        if item["config"].door_region is not None:
            entry["door_region"] = list(item["config"].door_region)
        cameras.append(entry)
    return {
        "type": "set_cameras",
        "v": 1,
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "cameras": cameras,
    }
