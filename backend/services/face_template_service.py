"""Template wajah dari CCTV, sisi backend (be-r14; docs/RENCANA-TEMPLATE-WAJAH.md).

Engine mengusulkan kandidat (`template.pull` -> `template.candidates`), backend
menyimpan, menimbang, menampilkan ke admin, lalu memasangnya pada jadwal
(`template.apply`) atau mencabutnya (`template.remove`). Kontrak:
contracts/schema/face_template.schema.json, ditangani sebelum validasi kontrak
produksi (seperti kontrak debug).

Saklar: `FACE_TEMPLATES_ENABLED` (env, rute + penarik) dan `active` di pengaturan
(penarikan dan penerapan terjadwal). Keduanya default mati.

Isi pesan engine tidak dipercaya: setiap item divalidasi terhadap skema sebelum
disimpan.
"""
from __future__ import annotations

import base64
import json
import logging
import math
import os
import secrets
import statistics
import struct
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from backend.core.database import add_settings_audit, connect, get_app_setting, init_database, set_app_setting

logger = logging.getLogger(__name__)

SETTING_KEY = "face_templates"
ENGINE_REPLY_SECONDS = 15.0
LIVE = ("pending", "queued", "review", "approved")
FINAL_WITHOUT_IMAGE = ("rejected", "discarded", "removed")
STATUSES = LIVE + ("applied", "failed") + FINAL_WITHOUT_IMAGE

DEFAULT_SETTINGS: Dict[str, Any] = {
    "active": False,
    # otomatis: queued diterapkan kecuali dibuang; persetujuan: hanya yang disetujui.
    "mode": "otomatis",
    "apply_time": "02:00",
    "review_margin": 0.15,
    "duplicate_similarity": 0.90,
    "outlier_drop": 0.15,
    "max_per_person_per_day": 5,
    "max_per_person": 30,
    "max_age_days": 30,
    "pull_interval_seconds": 60,
}

_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "contracts" / "schema" / "face_template.schema.json"


def templates_enabled() -> bool:
    return os.getenv("FACE_TEMPLATES_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


# ---------------------------------------------------------------------------
# pengaturan
# ---------------------------------------------------------------------------

def get_settings() -> Dict[str, Any]:
    stored = get_app_setting(SETTING_KEY, {}) or {}
    return {**DEFAULT_SETTINGS, **{k: v for k, v in stored.items() if k in DEFAULT_SETTINGS}}


def validate_settings(values: Dict[str, Any]) -> Dict[str, Any]:
    merged = {**get_settings(), **{k: v for k, v in values.items() if k in DEFAULT_SETTINGS}}
    if not isinstance(merged["active"], bool):
        raise ValueError("active harus true/false")
    if merged["mode"] not in ("otomatis", "persetujuan"):
        raise ValueError("mode harus 'otomatis' atau 'persetujuan'")
    try:
        datetime.strptime(str(merged["apply_time"]), "%H:%M")
    except ValueError as exc:
        raise ValueError("apply_time harus HH:MM") from exc
    for key, low, high in (("review_margin", 0.0, 1.0), ("duplicate_similarity", 0.5, 1.0),
                           ("outlier_drop", 0.0, 1.0)):
        value = merged[key]
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not low <= float(value) <= high:
            raise ValueError(f"{key} harus {low}..{high}")
        merged[key] = float(value)
    for key, low, high in (("max_per_person_per_day", 1, 50), ("max_per_person", 1, 200),
                           ("max_age_days", 1, 365), ("pull_interval_seconds", 10, 3600)):
        value = merged[key]
        if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
            raise ValueError(f"{key} harus bilangan bulat {low}..{high}")
    return merged


def save_settings(values: Dict[str, Any], actor: str) -> Dict[str, Any]:
    old = get_settings()
    new = validate_settings(values)
    set_app_setting(SETTING_KEY, new)
    add_settings_audit(actor, SETTING_KEY, old, new)
    return new


# ---------------------------------------------------------------------------
# vektor (tanpa numpy: backend tidak memasangnya)
# ---------------------------------------------------------------------------

def _decode(blob: Optional[bytes]) -> Optional[List[float]]:
    if not blob or len(blob) % 4:
        return None
    values = list(struct.unpack(f"<{len(blob) // 4}f", blob))
    norm = math.sqrt(sum(v * v for v in values))
    if not norm or not math.isfinite(norm):
        return None
    return [v / norm for v in values]


def _cos(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b)) if len(a) == len(b) else -1.0


# ---------------------------------------------------------------------------
# jembatan ke engine
# ---------------------------------------------------------------------------

class EngineTemplateLink:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: Dict[str, Dict[str, Any]] = {}
        self.engine_supported: Optional[bool] = None
        self.engine_reason: Optional[str] = None
        self.embedding_version: Optional[str] = None
        self._validator = None

    def _validate(self, message: Dict[str, Any]) -> List[str]:
        if self._validator is None:
            from jsonschema import Draft202012Validator

            self._validator = Draft202012Validator(json.loads(_SCHEMA_PATH.read_text(encoding="utf-8")))
        return [error.message for error in self._validator.iter_errors(message)][:3]

    def handle(self, message: Dict[str, Any]) -> bool:
        """True bila pesan ini urusan template (dan sudah ditangani)."""
        kind = message.get("type")
        if kind == "ack" and str(message.get("in_reply_to", "")).startswith("template."):
            self.engine_supported = False
            self.engine_reason = str(message.get("reason"))[:200]
            self._resolve(None, {"error": self.engine_reason})
            return True
        if not isinstance(kind, str) or not kind.startswith("template."):
            return False
        errors = self._validate(message)
        if errors:
            logger.warning("pesan %s dari engine tidak sah: %s", kind, errors)
            self._resolve(message.get("request_id"), {"error": f"pesan engine tidak sah: {errors[0]}"})
            return True
        self.engine_supported, self.engine_reason = True, None
        self._resolve(message.get("request_id"), message)
        return True

    def _resolve(self, request_id: Any, reply: Dict[str, Any]) -> None:
        with self._lock:
            if request_id is None:
                waiting = list(self._pending.values())
            else:
                waiting = [self._pending[request_id]] if request_id in self._pending else []
        for slot in waiting:
            slot["reply"] = reply
            slot["done"].set()

    def request(self, client: Any, message_type: str, **fields: Any) -> Dict[str, Any]:
        if not getattr(client, "connected", False):
            raise RuntimeError("Engine tidak tersambung")
        request_id = secrets.token_hex(8)
        slot = {"done": threading.Event(), "reply": None}
        with self._lock:
            self._pending[request_id] = slot
        try:
            client.send({"type": message_type, "v": 1, "ts": _ts(), "request_id": request_id, **fields})
            if not slot["done"].wait(ENGINE_REPLY_SECONDS):
                raise RuntimeError("Engine tidak menjawab permintaan template")
        finally:
            with self._lock:
                self._pending.pop(request_id, None)
        reply = slot["reply"] or {}
        if "error" in reply:
            raise RuntimeError(f"Engine menolak: {reply['error']}")
        return reply


engine_templates = EngineTemplateLink()


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


# ---------------------------------------------------------------------------
# penyimpanan
# ---------------------------------------------------------------------------

_COLUMNS = ("id, candidate_id, person_id, camera_id, captured_at, track_uuid, embedding_version, "
            "anchor_similarity, margin, runner_up_id, runner_up_similarity, face_px, det_score, yaw, "
            "status, reason, reference_id, created_at, decided_by, decided_at, applied_at, "
            "jpeg IS NOT NULL AS has_image")


def _row(cursor: Any, row: Sequence[Any]) -> Dict[str, Any]:
    item = {column[0]: value for column, value in zip(cursor.description, row)}
    item["has_image"] = bool(item.get("has_image"))
    return item


def store_candidates(items: Sequence[Dict[str, Any]], embedding_version: str,
                     now: Optional[float] = None) -> int:
    init_database()
    now = time.time() if now is None else now
    stored = 0
    with connect() as conn:
        for item in items:
            try:
                jpeg = base64.b64decode(item["jpeg_b64"], validate=True)
                embedding = base64.b64decode(item["embedding_b64"], validate=True)
            except (KeyError, ValueError, TypeError):
                continue
            cursor = conn.execute(
                "INSERT OR IGNORE INTO face_template_candidates (candidate_id, person_id, camera_id, "
                "captured_at, track_uuid, embedding_version, jpeg, embedding, anchor_similarity, margin, "
                "runner_up_id, runner_up_similarity, face_px, det_score, yaw, status, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'pending',?)",
                (item["candidate_id"], item["person_id"], item["camera_id"], item["captured_at"],
                 item.get("track_uuid"), embedding_version, jpeg, embedding,
                 float(item["anchor_similarity"]), float(item["margin"]), item.get("runner_up_id"),
                 item.get("runner_up_similarity"), float(item["face_px"]), float(item["det_score"]),
                 item.get("yaw"), now),
            )
            stored += cursor.rowcount
    return stored


def list_candidates(status: Optional[str] = None, person_id: Optional[str] = None,
                    limit: int = 200) -> List[Dict[str, Any]]:
    init_database()
    query = f"SELECT {_COLUMNS} FROM face_template_candidates WHERE 1=1"
    params: List[Any] = []
    if status:
        query += " AND status = ?"
        params.append(status)
    if person_id:
        query += " AND person_id = ?"
        params.append(person_id)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(max(1, min(1000, int(limit))))
    with connect() as conn:
        cursor = conn.execute(query, params)
        return [_row(cursor, row) for row in cursor.fetchall()]


def get_candidate(candidate_pk: int) -> Optional[Dict[str, Any]]:
    init_database()
    with connect() as conn:
        cursor = conn.execute(f"SELECT {_COLUMNS} FROM face_template_candidates WHERE id = ?", (candidate_pk,))
        row = cursor.fetchone()
        return _row(cursor, row) if row else None


def get_image(candidate_pk: int) -> Optional[bytes]:
    init_database()
    with connect() as conn:
        row = conn.execute("SELECT jpeg FROM face_template_candidates WHERE id = ?", (candidate_pk,)).fetchone()
    return bytes(row[0]) if row and row[0] else None


def status_counts() -> Dict[str, int]:
    init_database()
    with connect() as conn:
        rows = conn.execute("SELECT status, COUNT(*) FROM face_template_candidates GROUP BY status").fetchall()
    return {status: count for status, count in rows}


def _set_status(conn: Any, pk: int, status: str, reason: Optional[str] = None,
                actor: Optional[str] = None, now: Optional[float] = None, **extra: Any) -> None:
    now = time.time() if now is None else now
    fields = {"status": status, "reason": reason, "decided_at": now, **extra}
    if actor is not None:
        fields["decided_by"] = actor
    if status in FINAL_WITHOUT_IMAGE:
        fields["jpeg"] = None
        fields["embedding"] = None
    assignments = ", ".join(f"{key} = ?" for key in fields)
    conn.execute(f"UPDATE face_template_candidates SET {assignments} WHERE id = ?", (*fields.values(), pk))


# ---------------------------------------------------------------------------
# penimbang
# ---------------------------------------------------------------------------

def weigh_pending(settings: Optional[Dict[str, Any]] = None, engine_version: Optional[str] = None,
                  now: Optional[float] = None) -> Dict[str, int]:
    """Timbang semua kandidat `pending`. -> hitungan per hasil."""
    settings = settings or get_settings()
    now = time.time() if now is None else now
    since = now - 86400.0
    result: Dict[str, int] = {}
    init_database()
    with connect() as conn:
        pending = conn.execute(
            "SELECT id, person_id, embedding_version, embedding, margin FROM face_template_candidates "
            "WHERE status = 'pending' ORDER BY id").fetchall()
        for pk, person_id, version, blob, margin in pending:
            outcome, reason = _weigh_one(conn, pk, person_id, version, blob, margin, settings,
                                         engine_version, since)
            _set_status(conn, pk, outcome, reason, now=now)
            key = f"{outcome}:{reason}" if reason else outcome
            result[key] = result.get(key, 0) + 1
    return result


def _weigh_one(conn: Any, pk: int, person_id: str, version: str, blob: Optional[bytes], margin: float,
               settings: Dict[str, Any], engine_version: Optional[str], since: float) -> Tuple[str, Optional[str]]:
    if engine_version and version != engine_version:
        return "rejected", "versi_berbeda"
    vector = _decode(blob)
    if vector is None:
        return "rejected", "embedding_rusak"
    others = conn.execute(
        "SELECT id, status, embedding FROM face_template_candidates WHERE person_id = ? AND id != ? "
        "AND embedding IS NOT NULL AND embedding_version = ? "
        "AND (status = 'applied' OR (status IN ('pending','queued','review','approved') AND created_at >= ?))",
        (person_id, pk, version, since)).fetchall()
    decoded = [(other_pk, status, _decode(other_blob)) for other_pk, status, other_blob in others]
    decoded = [(other_pk, status, other) for other_pk, status, other in decoded if other is not None]
    # Duplikat hanya terhadap yang sudah lolos atau terpasang; antar `pending` diputuskan berurutan.
    for other_pk, status, other in decoded:
        if status != "pending" and _cos(vector, other) > settings["duplicate_similarity"]:
            return "rejected", "duplikat"
    peers = [other for _, status, other in decoded if status != "applied"]
    if len(peers) >= 3:
        group = peers + [vector]
        means = [statistics.fmean(_cos(a, b) for j, b in enumerate(group) if j != i) for i, a in enumerate(group)]
        if means[-1] < statistics.median(means) - settings["outlier_drop"]:
            return "rejected", "pencilan"
    accepted_today = sum(1 for _, status, _ in decoded if status in ("queued", "approved"))
    accepted_today += conn.execute(
        "SELECT COUNT(*) FROM face_template_candidates WHERE person_id = ? AND status = 'applied' "
        "AND created_at >= ?", (person_id, since)).fetchone()[0]
    if accepted_today >= settings["max_per_person_per_day"]:
        return "rejected", "batas_harian"
    if float(margin) < settings["review_margin"]:
        return "review", "margin_tipis"
    return "queued", None


# ---------------------------------------------------------------------------
# keputusan admin
# ---------------------------------------------------------------------------

def approve(candidate_pk: int, actor: str) -> Dict[str, Any]:
    item = get_candidate(candidate_pk)
    if item is None:
        raise LookupError("kandidat tidak ada")
    if item["status"] not in ("pending", "queued", "review"):
        raise ValueError(f"kandidat berstatus {item['status']} tidak bisa disetujui")
    with connect() as conn:
        _set_status(conn, candidate_pk, "approved", None, actor=actor)
    add_settings_audit(actor, "face_template.approve", item["status"], {"id": candidate_pk,
                                                                        "person_id": item["person_id"]})
    return get_candidate(candidate_pk) or {}


def discard(candidate_pk: int, actor: str, client: Any = None) -> Dict[str, Any]:
    """Buang kandidat. Yang sudah terpasang dicabut dulu dari engine."""
    item = get_candidate(candidate_pk)
    if item is None:
        raise LookupError("kandidat tidak ada")
    if item["status"] in FINAL_WITHOUT_IMAGE:
        return item
    status = "discarded"
    if item["status"] == "applied":
        if item.get("reference_id"):
            engine_templates.request(client, "template.remove", reference_ids=[int(item["reference_id"])])
        status = "removed"
    with connect() as conn:
        _set_status(conn, candidate_pk, status, "dibuang_admin", actor=actor)
    add_settings_audit(actor, "face_template.discard", item["status"], {"id": candidate_pk,
                                                                        "person_id": item["person_id"]})
    return get_candidate(candidate_pk) or {}


# ---------------------------------------------------------------------------
# tarik, pasang, kedaluwarsa
# ---------------------------------------------------------------------------

def pull_once(client: Any, max_items: int = 20) -> int:
    reply = engine_templates.request(client, "template.pull", max_items=max_items)
    engine_templates.embedding_version = reply.get("embedding_version")
    return store_candidates(reply.get("items") or [], str(reply.get("embedding_version")))


def apply_due(client: Any, settings: Optional[Dict[str, Any]] = None, actor: str = "jadwal",
              now: Optional[float] = None) -> Dict[str, int]:
    """Pasang yang siap (otomatis: queued + approved; persetujuan: approved), lalu cabut yang kedaluwarsa."""
    settings = settings or get_settings()
    now = time.time() if now is None else now
    statuses = ("approved",) if settings["mode"] == "persetujuan" else ("queued", "approved")
    marks = ",".join("?" * len(statuses))
    with connect() as conn:
        rows = conn.execute(
            f"SELECT id, candidate_id, person_id, jpeg, embedding, embedding_version, camera_id, captured_at "
            f"FROM face_template_candidates WHERE status IN ({marks}) AND jpeg IS NOT NULL ORDER BY id",
            statuses).fetchall()
    summary = {"applied": 0, "failed": 0, "removed": 0}
    for start in range(0, len(rows), 50):
        batch = rows[start:start + 50]
        by_candidate = {row[1]: row[0] for row in batch}
        reply = engine_templates.request(client, "template.apply", items=[{
            "candidate_id": candidate_id, "person_id": person_id,
            "jpeg_b64": base64.b64encode(jpeg).decode("ascii"),
            "embedding_b64": base64.b64encode(embedding).decode("ascii"),
            "embedding_version": version, "camera_id": camera_id, "captured_at": captured_at,
        } for _, candidate_id, person_id, jpeg, embedding, version, camera_id, captured_at in batch])
        with connect() as conn:
            for result in reply.get("items") or []:
                pk = by_candidate.get(result.get("candidate_id"))
                if pk is None:
                    continue
                if result.get("accepted"):
                    _set_status(conn, pk, "applied", None, now=now, reference_id=result.get("reference_id"),
                                applied_at=now)
                    summary["applied"] += 1
                else:
                    _set_status(conn, pk, "failed", str(result.get("reason") or "ditolak_engine")[:200], now=now)
                    summary["failed"] += 1
    summary["removed"] = remove_expired(client, settings, now=now)
    if any(summary.values()):
        add_settings_audit(actor, "face_template.apply", None, summary)
    return summary


def remove_expired(client: Any, settings: Dict[str, Any], now: Optional[float] = None) -> int:
    """Cabut template yang melewati umur, dan yang melebihi batas per orang (tertua dulu)."""
    now = time.time() if now is None else now
    cutoff = now - settings["max_age_days"] * 86400.0
    with connect() as conn:
        expired = conn.execute(
            "SELECT id, reference_id FROM face_template_candidates WHERE status = 'applied' AND applied_at < ?",
            (cutoff,)).fetchall()
        rows = conn.execute(
            "SELECT id, reference_id, person_id FROM face_template_candidates WHERE status = 'applied' "
            "AND applied_at >= ? ORDER BY person_id, applied_at DESC", (cutoff,)).fetchall()
    seen: Dict[str, int] = {}
    excess = []
    for pk, reference_id, person_id in rows:
        seen[person_id] = seen.get(person_id, 0) + 1
        if seen[person_id] > settings["max_per_person"]:
            excess.append((pk, reference_id))
    targets = [(pk, ref, "kedaluwarsa") for pk, ref in expired] + [(pk, ref, "melebihi_batas") for pk, ref in excess]
    if not targets:
        return 0
    reference_ids = [int(ref) for _, ref, _ in targets if ref]
    for start in range(0, len(reference_ids), 500):
        engine_templates.request(client, "template.remove", reference_ids=reference_ids[start:start + 500])
    with connect() as conn:
        for pk, _, reason in targets:
            _set_status(conn, pk, "removed", reason, now=now)
    return len(targets)


# ---------------------------------------------------------------------------
# penjadwal
# ---------------------------------------------------------------------------

class FaceTemplateScheduler:
    def __init__(self, client_provider: Any) -> None:
        self._client_provider = client_provider
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_pull = 0.0
        self.last_error: Optional[str] = None
        self.last_apply: Optional[Dict[str, Any]] = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="face-template-scheduler")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        self._thread = None

    def _run(self) -> None:
        while not self._stop.wait(10):
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001 - penjadwal tidak boleh mati
                self.last_error = str(exc)[:300]
                logger.warning("template wajah: %s", exc)

    def tick(self, now: Optional[float] = None) -> None:
        settings = get_settings()
        if not settings["active"]:
            return
        now = time.time() if now is None else now
        client = self._client_provider()
        if now - self._last_pull >= settings["pull_interval_seconds"] and getattr(client, "connected", False):
            self._last_pull = now
            pull_once(client)
            weigh_pending(settings, engine_templates.embedding_version, now=now)
            self.last_error = None
        if self._apply_due_now(settings, now) and getattr(client, "connected", False):
            from backend.services.break_policy import break_policy

            today = datetime.fromtimestamp(now, break_policy.timezone).date().isoformat()
            set_app_setting("face_templates_last_apply", today)
            self.last_apply = {"at": now, **apply_due(client, settings, now=now)}

    @staticmethod
    def _apply_due_now(settings: Dict[str, Any], now: float) -> bool:
        from backend.services.break_policy import break_policy

        local = datetime.fromtimestamp(now, break_policy.timezone)
        if local.strftime("%H:%M") < settings["apply_time"]:
            return False
        return get_app_setting("face_templates_last_apply") != local.date().isoformat()


def _engine_client() -> Any:
    from backend.services.engine_client import engine_client

    return engine_client


face_template_scheduler = FaceTemplateScheduler(_engine_client)
