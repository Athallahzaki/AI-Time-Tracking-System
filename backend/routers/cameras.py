from __future__ import annotations

from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.core.config import settings
from backend.services.engine_client import EngineConnectionError, engine_client
from backend.core.state import system_state

router = APIRouter(prefix="/api/cameras", tags=["Cameras"])


class SwitchSourceRequest(BaseModel):
    source_uri: str


_overrides: dict[str, dict] = {}


def _configured_cameras() -> list[dict]:
    cameras = []
    for camera_id, config in settings.cameras.items():
        override = _overrides.get(camera_id, {})
        activity = system_state.get_camera_activity(camera_id)
        recently_updated = (
            datetime.now(timezone.utc).timestamp() - float(activity.get("last_update", 0))
        ) < 12.0
        cameras.append({
            "id": camera_id,
            "code": config.code,
            "name": config.name,
            "source_uri": override.get("source_uri", config.source_uri),
            "stream_url": config.stream_url,
            "enabled": override.get("enabled", config.enabled_by_default),
            "is_running": bool(recently_updated),
            "fps": activity.get("fps", config.fps),
            "active_people": activity.get("people_count", 0) if recently_updated else 0,
            "stream_status": activity.get("stream_status", "Standby"),
        })
    return cameras


def _reconcile() -> None:
    if not engine_client.connected:
        raise HTTPException(status_code=503, detail="Engine is not connected")
    payload = {
        "type": "set_cameras",
        "v": 1,
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "cameras": [
            {
                "camera_id": camera["id"],
                "uri": camera["source_uri"],
                "enabled": camera["enabled"],
            }
            for camera in _configured_cameras()
        ],
    }
    try:
        engine_client.send(payload)
    except EngineConnectionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("")
def list_cameras():
    """Returns the list of all configured cameras along with their real-time status."""
    return {
        "status": "success",
        "cameras": _configured_cameras(),
    }


@router.get("/{camera_id}")
def get_camera_detail(camera_id: str):
    """Returns details for a specific camera channel."""
    cameras = _configured_cameras()
    for cam in cameras:
        if cam["id"] == camera_id:
            return cam
    raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")


@router.post("/{camera_id}/start")
def start_camera(camera_id: str):
    """Starts the AI vision processing worker for a camera."""
    if camera_id not in settings.cameras:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")
    _overrides.setdefault(camera_id, {})["enabled"] = True
    _reconcile()
    return {"status": "success", "message": f"Camera '{camera_id}' started"}


@router.post("/{camera_id}/stop")
def stop_camera(camera_id: str):
    """Stops the AI vision processing worker for a camera."""
    if camera_id not in settings.cameras:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")
    _overrides.setdefault(camera_id, {})["enabled"] = False
    _reconcile()
    return {"status": "success", "message": f"Camera '{camera_id}' stopped"}


@router.post("/{camera_id}/source")
def switch_camera_source(camera_id: str, req: SwitchSourceRequest):
    """Dynamically updates the video stream source and restarts the engine for that camera."""
    if camera_id not in settings.cameras:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")
    _overrides.setdefault(camera_id, {})["source_uri"] = req.source_uri
    _reconcile()
    return {
        "status": "success",
        "message": f"Switched source for camera '{camera_id}' to '{req.source_uri}'",
    }
