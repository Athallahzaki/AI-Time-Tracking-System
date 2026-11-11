"""Layanan panel debug: log bersama, jembatan kontrak debug ke engine, dan sesi debug.

Fase 1 (log backend + browser) dan Fase 2 (log engine, crop) berbagi buffer log
yang sama. Semua di memori: hilang saat backend restart, dan memang begitu
maksudnya. Crop TIDAK pernah disimpan di sini; ia hanya lewat.
"""
from __future__ import annotations

import logging
import os
import secrets
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, Optional

logger = logging.getLogger(__name__)

LOG_CAPACITY = 1000
LOGS: Deque[Dict[str, Any]] = deque(maxlen=LOG_CAPACITY)

DEBUG_SESSION_SECONDS = 30 * 60      # mode debug mati sendiri: risiko terbesarnya adalah lupa dimatikan
ENGINE_REPLY_SECONDS = 5.0


def debug_panel_enabled() -> bool:
    return os.getenv("DEBUG_PANEL_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


class _RingHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            LOGS.append({
                "ts": record.created, "source": "backend", "level": record.levelname,
                "logger": record.name, "message": record.getMessage()[:2000],
            })
        except Exception:   # log tidak boleh menjatuhkan pemanggilnya
            pass


def install_log_capture() -> None:
    root = logging.getLogger()
    if not any(isinstance(handler, _RingHandler) for handler in root.handlers):
        root.addHandler(_RingHandler(level=logging.INFO))


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class EngineDebugLink:
    """Sisi backend kontrak debug sementara (contracts/schema/debug.schema.json)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: Dict[str, Dict[str, Any]] = {}
        # None = belum tahu; False + alasan = engine menolak (lama, atau debug.enabled: false).
        self.engine_supported: Optional[bool] = None
        self.engine_reason: Optional[str] = None

    def subscribe(self, client: Any) -> None:
        """Dipanggil tiap kali backend tersambung ke engine, bila panel debug menyala."""
        self.engine_supported, self.engine_reason = None, None
        client.send({"type": "debug.subscribe", "v": 1, "ts": _ts(), "enabled": True})

    def handle(self, message: Dict[str, Any]) -> bool:
        """True bila pesan ini urusan debug (dan sudah ditangani). Isi pesan tidak dipercaya."""
        kind = message.get("type")
        if kind == "ack" and str(message.get("in_reply_to", "")).startswith("debug."):
            if message.get("in_reply_to") == "debug.subscribe":
                self.engine_supported = message.get("accepted") is True
                self.engine_reason = None if self.engine_supported else str(message.get("reason"))[:200]
            else:
                self._resolve(None, {"error": str(message.get("reason"))[:200]})
            return True
        if not isinstance(kind, str) or not kind.startswith("debug."):
            return False
        if kind == "debug.log":
            level = message.get("level")
            LOGS.append({
                "ts": time.time(), "source": "engine",
                "level": level if level in ("WARNING", "ERROR", "CRITICAL") else "ERROR",
                "logger": str(message.get("logger", ""))[:200], "message": str(message.get("message", ""))[:2000],
            })
        elif kind in ("debug.crops", "debug.crop"):
            self._resolve(message.get("request_id"), message)
        return True

    def _resolve(self, request_id: Any, reply: Dict[str, Any]) -> None:
        with self._lock:
            if request_id is None:      # penolakan tanpa request_id: berlaku untuk semua yang menunggu
                waiting = list(self._pending.values())
            else:
                waiting = [self._pending[request_id]] if request_id in self._pending else []
        for slot in waiting:
            slot["reply"] = reply
            slot["done"].set()

    def request(self, client: Any, message_type: str, **fields: Any) -> Dict[str, Any]:
        """Kirim permintaan debug dan tunggu balasannya. Melempar RuntimeError dengan alasan yang bisa ditampilkan."""
        if self.engine_supported is False:
            raise RuntimeError(f"Engine menolak debug: {self.engine_reason}")
        request_id = secrets.token_hex(8)
        slot = {"done": threading.Event(), "reply": None}
        with self._lock:
            self._pending[request_id] = slot
        try:
            client.send({"type": message_type, "v": 1, "ts": _ts(), "request_id": request_id, **fields})
            if not slot["done"].wait(ENGINE_REPLY_SECONDS):
                raise RuntimeError("Engine tidak menjawab permintaan debug")
        finally:
            with self._lock:
                self._pending.pop(request_id, None)
        reply = slot["reply"] or {}
        if "error" in reply:
            raise RuntimeError(f"Engine menolak: {reply['error']}")
        return reply


class DebugSessions:
    """Mode debug per sesi login: dibuka dengan password sendiri, mati sendiri setelah 30 menit."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._expires: Dict[str, float] = {}

    def open(self, session_hash: str, now: Optional[float] = None) -> float:
        now = time.time() if now is None else now
        with self._lock:
            self._expires = {key: value for key, value in self._expires.items() if value > now}
            self._expires[session_hash] = now + DEBUG_SESSION_SECONDS
            return self._expires[session_hash]

    def expires_at(self, session_hash: str, now: Optional[float] = None) -> Optional[float]:
        now = time.time() if now is None else now
        with self._lock:
            expires = self._expires.get(session_hash)
        return expires if expires is not None and expires > now else None

    def close(self, session_hash: str) -> None:
        with self._lock:
            self._expires.pop(session_hash, None)


engine_debug = EngineDebugLink()
debug_sessions = DebugSessions()
