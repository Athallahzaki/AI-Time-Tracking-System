"""Satu sumber kebenaran untuk state kamera yang DIINGINKAN.

Sebelumnya ada dua: `cameras.yaml` (dipakai saat reconnect) dan `_overrides`
di memori router (dipakai saat operator menekan start/stop). Setelah engine
reconnect, perubahan operator dibatalkan diam-diam; setelah backend restart,
hilang. Sekarang override operator disimpan di SQLite dan kedua jalur memanggil
fungsi yang sama.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from backend.core.config import CameraConfig, settings
from backend.core.database import get_camera_overrides


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
            "enabled": bool(override.get("enabled", config.enabled_by_default)),
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
