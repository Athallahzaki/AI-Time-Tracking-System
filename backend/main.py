import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from backend.engine_service import EngineService


app = FastAPI(
    title="AI Time Tracking API"
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
# START ENGINE
# ==========================================

@app.on_event("startup")
async def startup():

    print("Starting Engine Service...")

    engine_service.start()


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