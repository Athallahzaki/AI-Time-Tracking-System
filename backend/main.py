import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from backend.engine_service import EngineService


# ==========================================
# VIDEO SOURCE
# ==========================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]

VIDEO_PATH = (
    PROJECT_ROOT
    / "frontend"
    / "public"
    / "videos"
    / "video2.mp4"
)


# ==========================================
# ENGINE
# ==========================================

engine_service = EngineService(
    source=str(VIDEO_PATH)
)


# ==========================================
# LIFESPAN (replaces deprecated on_event)
# ==========================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Starts the engine on server startup and stops it cleanly on shutdown."""
    print("Starting Engine Service...")
    engine_service.start()
    yield
    engine_service.stop()


app = FastAPI(
    title="AI Time Tracking API",
    lifespan=lifespan,
)


# ==========================================
# CORS
# ==========================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==========================================
# TEST API
# ==========================================

@app.get("/")
def root():

    return {
        "status": "online",
        "engine": engine_service.running,
    }


# ==========================================
# SSE
# ==========================================

@app.get("/api/detections/stream")
async def detection_stream(request: Request):

    client_queue = engine_service.subscribe()

    async def event_generator():

        try:

            while True:

                if await request.is_disconnected():
                    break

                try:

                    data = await asyncio.to_thread(
                        client_queue.get,
                        True,
                        1.0
                    )

                    yield {
                        "event": "detection",
                        "data": json.dumps(data),
                    }

                except Exception:
                    continue

        finally:

            engine_service.unsubscribe(
                client_queue
            )

    return EventSourceResponse(
        event_generator()
    )