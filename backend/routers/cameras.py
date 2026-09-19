from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.services.camera_manager import camera_manager

router = APIRouter(prefix="/api/cameras", tags=["Cameras"])


class SwitchSourceRequest(BaseModel):
    source_uri: str


@router.get("")
def list_cameras():
    """Returns the list of all configured cameras along with their real-time status."""
    return {
        "status": "success",
        "cameras": camera_manager.get_camera_list(),
    }


@router.get("/{camera_id}")
def get_camera_detail(camera_id: str):
    """Returns details for a specific camera channel."""
    cameras = camera_manager.get_camera_list()
    for cam in cameras:
        if cam["id"] == camera_id:
            return cam
    raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")


@router.post("/{camera_id}/start")
def start_camera(camera_id: str):
    """Starts the AI vision processing worker for a camera."""
    success = camera_manager.start_worker(camera_id)
    if not success:
        raise HTTPException(status_code=400, detail=f"Failed to start camera '{camera_id}'")
    return {"status": "success", "message": f"Camera '{camera_id}' started"}


@router.post("/{camera_id}/stop")
def stop_camera(camera_id: str):
    """Stops the AI vision processing worker for a camera."""
    success = camera_manager.stop_worker(camera_id)
    if not success:
        raise HTTPException(status_code=400, detail=f"Failed to stop camera '{camera_id}' or not running")
    return {"status": "success", "message": f"Camera '{camera_id}' stopped"}


@router.post("/{camera_id}/source")
def switch_camera_source(camera_id: str, req: SwitchSourceRequest):
    """Dynamically updates the video stream source and restarts the engine for that camera."""
    success = camera_manager.switch_source(camera_id, req.source_uri)
    if not success:
        raise HTTPException(status_code=400, detail=f"Failed to switch source for camera '{camera_id}'")
    return {
        "status": "success",
        "message": f"Switched source for camera '{camera_id}' to '{req.source_uri}'",
    }
