"""Panel debug admin (docs/ANALISIS-KETAHANAN.md §6).

Terdaftar HANYA bila `DEBUG_PANEL_ENABLED` diisi (lihat `main.py`); tanpa itu
rutenya tidak ada.

Fase 1 (kesehatan, log, rekaman CSV): tanpa perubahan kontrak; isinya angka dan
pesan galat, jadi cukup `require_admin`.

Fase 2 (log engine, crop tubuh): memakai kontrak debug sementara
(`contracts/schema/debug.schema.json`). Crop adalah data biometrik, jadi butuh
izin per orang (`can_debug`), konfirmasi ulang password sendiri, sesi debug 30
menit yang mati sendiri, alasan wajib, dan audit per crop.
"""
from __future__ import annotations

import csv
import io
import logging
import threading
import time
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from backend.core.database import add_settings_audit, get_protocol_events, get_user_by_id
from backend.core.security import require_admin, require_user, session_token
from backend.services.auth_service import auth_service
from backend.services.debug_service import (  # noqa: F401 — diekspor ulang untuk main.py dan tes
    LOG_CAPACITY,
    LOGS as _LOGS,
    _RingHandler,
    debug_panel_enabled,
    debug_sessions,
    engine_debug,
    install_log_capture,
)
from backend.services.engine_client import engine_client

router = APIRouter(prefix="/api/debug", tags=["Debug"])


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
    source: Optional[Literal["backend", "frontend", "engine"]] = None,
    min_level: Literal["INFO", "WARNING", "ERROR"] = "INFO",
    limit: int = Query(200, ge=1, le=LOG_CAPACITY),
    _admin=Depends(require_admin),
):
    """Log backend, galat browser, dan (Fase 2) log WARNING engine dalam satu daftar, terbaru dulu."""
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


# ---------------------------------------------------------------- Fase 2

PASSWORD_ATTEMPTS = 5
PASSWORD_LOCK_SECONDS = 300
_failures: Dict[int, List[float]] = {}
_failures_lock = threading.Lock()


def _too_many_failures(user_id: int, now: float) -> bool:
    with _failures_lock:
        recent = [at for at in _failures.get(user_id, []) if now - at < PASSWORD_LOCK_SECONDS]
        _failures[user_id] = recent
        return len(recent) >= PASSWORD_ATTEMPTS


def require_debug_session(admin=Depends(require_admin), token: str = Depends(session_token)):
    """Admin + mode debug yang masih terbuka pada sesi login INI."""
    if debug_sessions.expires_at(auth_service.hash_token(token)) is None:
        raise HTTPException(status_code=403, detail="Mode debug belum dibuka atau sudah berakhir")
    return admin


class DebugSessionRequest(BaseModel):
    password: str = Field(min_length=1, max_length=256)


@router.get("/session")
def debug_session_status(admin=Depends(require_admin), token: str = Depends(session_token)):
    account = get_user_by_id(admin["id"]) or {}
    return {
        "status": "success",
        "can_debug": bool(account.get("can_debug")),
        "active_until": debug_sessions.expires_at(auth_service.hash_token(token)),
        "engine_supported": engine_debug.engine_supported,
        "engine_reason": engine_debug.engine_reason,
    }


@router.post("/session")
def open_debug_session(req: DebugSessionRequest, admin=Depends(require_admin),
                       token: str = Depends(session_token)):
    """Buka mode debug dengan password SENDIRI (bukan kode bersama): tercatat atas nama
    orangnya, bisa dicabut per orang, dan mati sendiri setelah 30 menit."""
    now = time.time()
    account = get_user_by_id(admin["id"], include_password=True)
    if account is None or not account.get("can_debug"):
        raise HTTPException(status_code=403, detail="Akun ini tidak punya izin mode debug")
    if _too_many_failures(admin["id"], now):
        raise HTTPException(status_code=429, detail="Terlalu banyak percobaan. Coba lagi beberapa menit lagi.")
    if not auth_service.verify_password(req.password, account["password_hash"]):
        with _failures_lock:
            _failures.setdefault(admin["id"], []).append(now)
        add_settings_audit(admin["username"], "debug.session", None, "password salah")
        # 400, bukan 401/403: frontend mengartikan 401 sebagai sesi habis dan 403 sebagai salah peran.
        raise HTTPException(status_code=400, detail="Password salah")
    active_until = debug_sessions.open(auth_service.hash_token(token), now)
    add_settings_audit(admin["username"], "debug.session", None, "dibuka")
    return {"status": "success", "active_until": active_until}


@router.delete("/session", status_code=204)
def close_debug_session(admin=Depends(require_admin), token: str = Depends(session_token)):
    debug_sessions.close(auth_service.hash_token(token))
    add_settings_audit(admin["username"], "debug.session", None, "ditutup")
    return None


def _ask_engine(message_type: str, **fields: Any) -> Dict[str, Any]:
    if not engine_client.connected:
        raise HTTPException(status_code=503, detail="Engine tidak tersambung")
    try:
        return engine_debug.request(engine_client, message_type, **fields)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:  # noqa: BLE001 — koneksi putus saat mengirim
        raise HTTPException(status_code=503, detail="Engine tidak dapat dihubungi") from error


@router.get("/crops")
def list_crops(_admin=Depends(require_debug_session)):
    """Track yang crop tubuhnya masih ada di memori engine (tanpa gambar)."""
    crops = _ask_engine("debug.crop_list").get("crops")
    return {"status": "success", "crops": crops if isinstance(crops, list) else []}


class CropRequest(BaseModel):
    track_uuid: str = Field(pattern=r"^tr_[A-Za-z0-9_-]{1,64}$")
    reason: str = Field(min_length=5, max_length=300)


@router.post("/crop")
def view_crop(req: CropRequest, admin=Depends(require_debug_session)):
    """Gambar crop terakhir yang dinilai ReID untuk satu track. Dicatat SEBELUM diminta;
    tidak disimpan di backend dan tidak boleh di-cache browser."""
    add_settings_audit(admin["username"], "debug.crop", None,
                       {"track_uuid": req.track_uuid, "reason": req.reason})
    reply = _ask_engine("debug.crop_request", track_uuid=req.track_uuid)
    found = reply.get("found") is True and isinstance(reply.get("jpeg_b64"), str)
    body = {"status": "success", "found": found, "track_uuid": req.track_uuid}
    if found:
        body.update({key: reply.get(key) for key in ("camera_id", "at", "width", "height", "jpeg_b64")})
    return JSONResponse(body, headers={"Cache-Control": "no-store"})
