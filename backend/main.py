from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.core.config import settings
from backend.services.camera_manager import camera_manager
from backend.routers import attendance, cameras, stats, streams

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s]: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("AI-Time-Tracking-Backend")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager to start camera workers on startup and cleanup on shutdown."""
    logger.info("Initializing AI Time Tracking Backend...")
    camera_manager.start_default_cameras()
    yield
    logger.info("Shutting down AI Time Tracking Backend...")
    camera_manager.shutdown()


app = FastAPI(
    title="AI Time Tracking System API",
    description="Real-time multi-camera computer vision and attendance tracking backend.",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins + ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register Routers
app.include_router(streams.router)
app.include_router(cameras.router)
app.include_router(stats.router)
app.include_router(attendance.router)


@app.get("/")
def root():
    """Health check and overview of active workers and cameras."""
    active_workers = camera_manager.get_active_workers()
    return {
        "status": "online",
        "version": "2.0.0",
        "active_cameras_count": len(active_workers),
        "total_configured_cameras": len(camera_manager.get_camera_list()),
        "active_camera_ids": [w.camera_id for w in active_workers],
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)