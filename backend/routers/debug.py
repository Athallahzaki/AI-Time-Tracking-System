"""Panel debug admin, Fase 1 (docs/ANALISIS-KETAHANAN.md §6).

Terdaftar HANYA bila `DEBUG_PANEL_ENABLED` diisi (lihat `main.py`); tanpa itu
rutenya tidak ada. Tanpa perubahan kontrak: semua data engine di sini sudah
dikirim lewat `engine.health` dan `camera.*`, dan tersimpan di `protocol_events`.

Isinya angka dan pesan galat, bukan wajah: cukup `require_admin`.
"""
from __future__ import annotations

import csv
import io
import logging
import os
import time
from collections import deque
from typing import Any, Deque, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from backend.core.database import get_protocol_events
from backend.core.security import require_admin, require_user
from backend.services.engine_client import engine_client

router = APIRouter(prefix="/api/debug", tags=["Debug"])

LOG_CAPACITY = 1000
_LOGS: Deque[Dict[str, Any]] = deque(maxlen=LOG_CAPACITY)   # hilang saat restart: memang sementara


def debug_panel_enabled() -> bool:
    return os.getenv("DEBUG_PANEL_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


class _RingHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            _LOGS.append({
                "ts": record.created, "source": "backend", "level": record.levelname,
                "logger": record.name, "message": record.getMessage()[:2000],
            })
        except Exception:   # log tidak boleh menjatuhkan pemanggilnya
            pass


def install_log_capture() -> None:
    root = logging.getLogger()
    if not any(isinstance(handler, _RingHandler) for handler in root.handlers):
        root.addHandler(_RingHandler(level=logging.INFO))


def _health_events(limit: int, since: Optional[float] = None) -> List[Dict[str, Any]]:
    return get_protocol_events("engine.health", limit=limit, since_timestamp=since, newest_first=True)


def _per_minute(new: Dict[str, Any], old: Dict[str, Any], seconds: float) -> Dict[str, float]:
    """Laju per menit dari dua penghitung kumulatif. Negatif (engine restart) = dilewati."""
    out: Dict[str, float] = {}
    for key, value in new.items():
        before = old.get(key)
        if isinstance(value, (int, float)) and isinstance(before, (int, float)) and value >= before:
            out[key] = round((value - before) * 60.0 / seconds, 2)
    return out


@router.get("/health")
def health(_admin=Depends(require_admin)):
    """Keadaan engine sekarang: status per kamera, alasan gagal terakhir, dan LAJU
    (bukan total) penghitung. Laju nol yang tiba-tiba muncul = engine beku."""
    now = time.time()
    events = _health_events(2)
    latest = events[0] if events else None
    payload = latest["payload"] if latest else {}
    previous = events[1] if len(events) > 1 else None
    window = (latest["timestamp"] - previous["timestamp"]) if previous else 0.0

    # Kejadian kamera 24 jam terakhir, terbaru dulu: alasan gagal/turun terakhir per kamera.
    last_event: Dict[str, Dict[str, Any]] = {}
    for kind in ("camera.failed", "camera.degraded", "camera.online"):
        for event in get_protocol_events(kind, limit=200, since_timestamp=now - 86400.0, newest_first=True):
            camera_id = str(event["payload"].get("camera_id"))
            if camera_id not in last_event or event["timestamp"] > last_event[camera_id]["at"]:
                last_event[camera_id] = {
                    "type": kind, "at": event["timestamp"],
                    "reason": event["payload"].get("reason"),
                }

    metrics = payload.get("camera_metrics") or {}
    old_metrics = (previous["payload"].get("camera_metrics") or {}) if previous else {}
    cameras = []
    for camera_id, state in sorted((payload.get("cameras") or {}).items()):
        current = metrics.get(camera_id) or {}
        cameras.append({
            "camera_id": camera_id,
            "state": state,
            "metrics": current,
            "per_minute": _per_minute(current, old_metrics.get(camera_id) or {}, window) if window > 0 else {},
            "last_event": last_event.get(camera_id),
        })

    identity = payload.get("identity_metrics") or {}
    return {
        "status": "success",
        "engine_connected": bool(engine_client.connected),
        "last_event_seq": engine_client.last_event_seq,
        # Umur laporan kesehatan terakhir; engine mengirim tiap --health-seconds (default 30).
        "health_age_seconds": round(now - latest["timestamp"], 1) if latest else None,
        "window_seconds": round(window, 1),
        "engine": {key: payload.get(key) for key in (
            "models_loaded", "degraded_components", "queue_depth", "drop_rate",
            "outbox_depth", "disk_free_mb", "gpu_util", "vram_mb")},
        "cameras": cameras,
        "identity_metrics": identity,
        "identity_per_minute": _per_minute(
            identity, (previous["payload"].get("identity_metrics") or {}) if previous else {}, window,
        ) if window > 0 else {},
    }


@router.get("/health.csv")
def health_csv(
    start: float = Query(..., alias="from", description="epoch detik"),
    end: float = Query(..., alias="to", description="epoch detik"),
    _admin=Depends(require_admin),
):
    """Rekaman kesehatan satu rentang waktu, kolom seperti `scripts/lag_probe.py`
    (sumber `health`), jadi bisa langsung diberikan ke `scripts/summarize_gladi.py`."""
    rows = [event for event in reversed(_health_events(5000, since=start)) if event["timestamp"] <= end]
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["elapsed_s", "source", "camera_id", "fps", "dropped", "lag_s", "state", "ts"])
    for event in rows:
        payload = event["payload"]
        for camera_id, state in sorted((payload.get("cameras") or {}).items()):
            metric = (payload.get("camera_metrics") or {}).get(camera_id) or {}
            writer.writerow([
                round(event["timestamp"] - start, 3), "health", camera_id,
                metric.get("effective_fps", ""), metric.get("frames_dropped_stale", ""),
                metric.get("lag_seconds", ""), state, event["timestamp"],
            ])
    return Response(out.getvalue(), media_type="text/csv", headers={
        "Content-Disposition": 'attachment; filename="rekaman-kesehatan.csv"',
    })


@router.get("/logs")
def logs(
    source: Optional[Literal["backend", "frontend"]] = None,
    min_level: Literal["INFO", "WARNING", "ERROR"] = "INFO",
    limit: int = Query(200, ge=1, le=LOG_CAPACITY),
    _admin=Depends(require_admin),
):
    """Log backend dan galat frontend dalam satu daftar, terbaru dulu."""
    floor = logging.getLevelName(min_level)
    picked = [
        entry for entry in reversed(_LOGS)
        if (source is None or entry["source"] == source)
        and logging.getLevelName(entry["level"]) >= floor
    ]
    return {"status": "success", "logs": picked[:limit]}


class ClientLog(BaseModel):
    level: Literal["WARNING", "ERROR"] = "ERROR"
    message: str = Field(min_length=1, max_length=2000)
    url: str = Field(default="", max_length=500)


@router.post("/client-log", status_code=204)
def client_log(entry: ClientLog, user=Depends(require_user)):
    """Galat dari browser (window.onerror, WHEP, fetch). Semua pengguna yang login
    boleh melapor: galat di layar viewer sama bergunanya dengan di layar admin."""
    _LOGS.append({
        "ts": time.time(), "source": "frontend", "level": entry.level,
        "logger": str(user.get("username", "?")), "message": entry.message, "url": entry.url,
    })
    return None
