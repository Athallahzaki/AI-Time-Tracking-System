from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.core.config import settings
from backend.core.database import set_camera_override
from backend.core.security import require_api_key
from backend.core.state import system_state
from backend.services.camera_state import effective_cameras, set_cameras_message, source_allowed
from backend.services.engine_client import EngineConnectionError, engine_client
from backend.core.state import system_state

router = APIRouter(prefix="/api/cameras", tags=["Cameras"])


class SwitchSourceRequest(BaseModel):
    source_uri: str


def _configured_cameras() -> list[dict]:
    cameras = []
    now = time.time()
    for item in effective_cameras():
        config = item["config"]
        activity = system_state.get_camera_activity(item["camera_id"])
        recently_updated = (now - float(activity.get("last_update", 0))) < 12.0
        cameras.append({
            "id": item["camera_id"],
            "code": config.code,
            "name": config.name,
            "source_uri": item["source_uri"],
            "allowed_sources": [config.source_uri, *config.allowed_sources],
            "stream_url": config.stream_url,
            "enabled": item["enabled"],
            "door_region": config.door_region,
            "is_running": bool(recently_updated),
            "fps": activity.get("fps", config.fps),
            "active_people": activity.get("people_count", 0) if recently_updated else 0,
            "stream_status": activity.get("stream_status", "Standby"),
        })
    return cameras


def _push_desired_state() -> bool:
    """Send the whole desired set. The change is already persisted, so an
    offline engine simply receives it on the next reconnect."""
    if not engine_client.connected:
        return False
    try:
        engine_client.send(set_cameras_message())
        return True
    except EngineConnectionError:
        return False


def _require_camera(camera_id: str):
    config = settings.cameras.get(camera_id)
    if config is None:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")
    return config


@router.get("")
def list_cameras():
    return {"status": "success", "cameras": _configured_cameras()}


@router.get("/{camera_id}")
def get_camera_detail(camera_id: str):
    for cam in _configured_cameras():
        if cam["id"] == camera_id:
            return cam
    raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")


@router.post("/{camera_id}/start", dependencies=[Depends(require_api_key)])
def start_camera(camera_id: str):
    _require_camera(camera_id)
    set_camera_override(camera_id, enabled=True)
    applied = _push_desired_state()
    return {"status": "success", "applied_to_engine": applied,
            "message": f"Camera '{camera_id}' enabled"}


@router.post("/{camera_id}/stop", dependencies=[Depends(require_api_key)])
def stop_camera(camera_id: str):
    _require_camera(camera_id)
    set_camera_override(camera_id, enabled=False)
    applied = _push_desired_state()
    return {"status": "success", "applied_to_engine": applied,
            "message": f"Camera '{camera_id}' disabled"}


@router.post("/{camera_id}/source", dependencies=[Depends(require_api_key)])
def switch_camera_source(camera_id: str, req: SwitchSourceRequest):
    """Switch only to a source listed for this camera in cameras.yaml.

    The engine opens whatever URI it is given — a local path, an internal URL.
    Accepting free text here let any client make the engine machine open
    arbitrary files and hosts.
    """
    config = _require_camera(camera_id)
    if not source_allowed(config, req.source_uri):
        raise HTTPException(
            status_code=403,
            detail="source_uri is not in this camera's allowed_sources (cameras.yaml)",
        )
    set_camera_override(camera_id, source_uri=req.source_uri)
    applied = _push_desired_state()
    return {"status": "success", "applied_to_engine": applied,
            "message": f"Switched source for camera '{camera_id}'"}
