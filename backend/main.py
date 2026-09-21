from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.core.config import settings
from backend.core.database import init_database
from backend.routers import (
    attendance,
    cameras,
    enrollments,
    stats,
    streams,
    system,
)
from backend.services.engine_client import engine_client
from backend.services.engine_connection_manager import engine_connection_manager
from backend.services.engine_integration import (
    engine_integration,
)


logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s [%(levelname)s] "
        "[%(name)s]: %(message)s"
    ),
    datefmt="%H:%M:%S",
)

logger = logging.getLogger(
    "AI-Time-Tracking-Backend"
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "Initializing AI Time Tracking Backend..."
    )

    init_database()

    engine_integration.configure()

    engine_connection_manager.start()

    yield

    logger.info(
        "Shutting down AI Time Tracking Backend..."
    )

    engine_connection_manager.stop()


app = FastAPI(
    title="AI Time Tracking System API",
    description="AI Time Tracking backend.",
    version="2.0.0",
    lifespan=lifespan,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(attendance.router)
app.include_router(cameras.router)
app.include_router(enrollments.router)
app.include_router(stats.router)
app.include_router(streams.router)
app.include_router(system.router)


@app.get("/")
def root():
    return {
        "status": "online",
        "version": "2.0.0",
        "engine": (
            "connected"
            if engine_client.connected
            else "disconnected"
        ),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
