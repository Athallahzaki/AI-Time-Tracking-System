"""Backward compatibility wrapper for EngineService."""
from backend.services.engine_worker import EngineWorker
from backend.services.camera_manager import camera_manager

EngineService = EngineWorker

__all__ = ["EngineService", "EngineWorker", "camera_manager"]