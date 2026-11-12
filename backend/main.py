from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.core.security import require_api_key

from backend.core.config import settings
from backend.core.database import init_database
from backend.routers import (
    attendance,
    auth,
    cameras,
    debug,
    employees,
    enrollments,
    notifications,
    reports,
    hr_review,
    reviews,
    me,
    settings as settings_router,
    stats,
    streams,
    system,
    violations,
)

from backend.services.auth_service import (
    auth_service,
)

from backend.services.email_service import (
    email_service,
)
from backend.services.engine_client import engine_client
from backend.services.engine_connection_manager import engine_connection_manager
from backend.services.engine_integration import (
    detection_writer,
    engine_integration,
)
from backend.services.report_service import report_scheduler
from backend.services import face_template_service as face_templates


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

    if auth_service.bootstrap_admin():
        logger.info(
            "Initial admin user created"
        )
        
    # Fail at startup, loudly, on a broken cameras.yaml — never "no cameras".
    cameras = settings.cameras
    logger.info("Loaded %s camera(s) from %s", len(cameras), settings.cameras_yaml_path)

    engine_integration.configure()
    
    email_service.start()
    report_scheduler.start()
    engine_connection_manager.start()
    if face_templates.templates_enabled():
        face_templates.face_template_scheduler.start()

    yield

    logger.info(
        "Shutting down AI Time Tracking Backend..."
    )

    
    engine_connection_manager.stop()
    face_templates.face_template_scheduler.stop()
    report_scheduler.stop()
    email_service.stop()
    detection_writer.stop()


app = FastAPI(
    title="AI Time Tracking System API",
    description="AI Time Tracking backend.",
    version="2.1.0",
    lifespan=lifespan,
    # Dulu didefinisikan tetapi tidak dipasang di rute mana pun (kontrol palsu).
    dependencies=[Depends(require_api_key)],
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
app.include_router(employees.router)
app.include_router(enrollments.router)
app.include_router(settings_router.router)
app.include_router(stats.router)
app.include_router(streams.router)
app.include_router(system.router)
app.include_router(violations.router)
app.include_router(notifications.router)
app.include_router(auth.router)
app.include_router(reports.router)
app.include_router(hr_review.router)
app.include_router(reviews.router)
app.include_router(me.router)

# Panel debug admin: default mati. Mati = rutenya tidak terdaftar sama sekali.
if debug.debug_panel_enabled():
    debug.install_log_capture()
    engine_client.set_debug_handler(debug.engine_debug.handle)
    app.include_router(debug.router)

# Template wajah dari CCTV (docs/RENCANA-TEMPLATE-WAJAH.md): default mati, rute tidak terdaftar.
if face_templates.templates_enabled():
    from backend.routers import face_templates as face_templates_router

    engine_client.set_template_handler(face_templates.engine_templates.handle)
    app.include_router(face_templates_router.router)

@app.get("/")
def root():
    return {
        "status": "online",
        "version": "2.1.0",
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
