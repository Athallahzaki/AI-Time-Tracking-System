"""Menu "Template Wajah" (be-r14; docs/RENCANA-TEMPLATE-WAJAH.md §8).

Terdaftar HANYA bila `FACE_TEMPLATES_ENABLED` diisi (lihat `main.py`). Semua rute
admin. Gambar adalah crop wajah karyawan (data biometrik): tidak di-cache, dan
setiap keputusan admin masuk `settings_audit`.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import Response

from backend.core.security import require_admin
from backend.services import face_template_service as templates
from backend.services.engine_client import engine_client

router = APIRouter(prefix="/api/face-templates", tags=["Template Wajah"])


def _engine_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=503, detail=str(exc)[:300])


@router.get("/status")
def status(_admin=Depends(require_admin)) -> Dict[str, Any]:
    scheduler = templates.face_template_scheduler
    return {
        "settings": templates.get_settings(),
        "counts": templates.status_counts(),
        "engine_connected": bool(getattr(engine_client, "connected", False)),
        "engine_supported": templates.engine_templates.engine_supported,
        "engine_reason": templates.engine_templates.engine_reason,
        "embedding_version": templates.engine_templates.embedding_version,
        "last_apply": scheduler.last_apply,
        "last_error": scheduler.last_error,
    }


@router.put("/settings")
def put_settings(values: Dict[str, Any] = Body(...), admin=Depends(require_admin)) -> Dict[str, Any]:
    try:
        return templates.save_settings(values, admin["username"])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("")
def list_candidates(status: Optional[str] = Query(None), person_id: Optional[str] = Query(None),
                    limit: int = Query(200, ge=1, le=1000), _admin=Depends(require_admin)):
    if status is not None and status not in templates.STATUSES:
        raise HTTPException(status_code=422, detail="status tidak dikenal")
    return templates.list_candidates(status=status, person_id=person_id, limit=limit)


@router.get("/{candidate_pk}/image")
def image(candidate_pk: int, _admin=Depends(require_admin)):
    jpeg = templates.get_image(candidate_pk)
    if jpeg is None:
        raise HTTPException(status_code=404, detail="gambar tidak ada (dibuang atau ditolak)")
    return Response(content=jpeg, media_type="image/jpeg",
                    headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@router.post("/{candidate_pk}/approve")
def approve(candidate_pk: int, admin=Depends(require_admin)):
    try:
        return templates.approve(candidate_pk, admin["username"])
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{candidate_pk}/discard")
def discard(candidate_pk: int, admin=Depends(require_admin)):
    try:
        return templates.discard(candidate_pk, admin["username"], engine_client)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise _engine_error(exc) from exc


@router.post("/weigh")
def weigh(_admin=Depends(require_admin)):
    """Tarik kandidat dari engine (bila tersambung) lalu timbang yang `pending`."""
    pulled = None
    if getattr(engine_client, "connected", False):
        try:
            pulled = templates.pull_once(engine_client)
        except RuntimeError as exc:
            raise _engine_error(exc) from exc
    result = templates.weigh_pending(engine_version=templates.engine_templates.embedding_version)
    return {"pulled": pulled, "result": result}


@router.post("/apply-now")
def apply_now(admin=Depends(require_admin)):
    try:
        return templates.apply_due(engine_client, actor=admin["username"])
    except RuntimeError as exc:
        raise _engine_error(exc) from exc
