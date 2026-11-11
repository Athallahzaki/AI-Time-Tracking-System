"""Sisi engine dari kontrak debug sementara (contracts/schema/debug.schema.json).

Tiga hal, semuanya non-durabel dan hanya di memori:
- crop tubuh terakhir yang di-embed per track (cache LRU berbatas), untuk
  melihat BAGIAN MANA yang dinilai ReID;
- daftar dan gambar crop itu atas permintaan backend (balasan kontrol);
- log WARNING ke atas diteruskan lewat antrean view (best-effort).

Mati total kecuali `debug.enabled: true` di config engine. Menyala pun, tidak
ada yang dikirim sebelum backend mengirim `debug.subscribe` pada koneksi itu.
Crop adalah data biometrik: tidak pernah ditulis ke disk di sini, dan hilang
saat engine berhenti.
"""

from __future__ import annotations

import base64
import logging
import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Dict, Optional, Tuple

from ..api import events

LabelOf = Callable[[str], Optional[Tuple[Optional[str], Optional[str]]]]
_JPEG_QUALITY = 85


class _ForwardHandler(logging.Handler):
    def __init__(self, bridge: "DebugBridge") -> None:
        super().__init__(level=logging.WARNING)
        self._bridge = bridge
        self._busy = threading.local()

    def emit(self, record: logging.LogRecord) -> None:
        if getattr(self._busy, "on", False):
            return                      # log yang lahir dari pengiriman log: jangan berputar
        self._busy.on = True
        try:
            self._bridge.forward_log(record)
        except Exception:
            pass                        # log tidak boleh menjatuhkan pemanggilnya
        finally:
            self._busy.on = False


class DebugBridge:
    def __init__(self, api: Any, enabled: bool, capacity: int = 200,
                 label_of: Optional[LabelOf] = None) -> None:
        self.enabled = bool(enabled)
        self._api = api
        self._capacity = int(capacity)
        self._label_of = label_of
        self._crops: "OrderedDict[str, Tuple[str, float, Any]]" = OrderedDict()
        self._lock = threading.Lock()
        self._subscribed_generation: Optional[int] = None
        self._handler = _ForwardHandler(self)

    # -- dipanggil thread kamera (ReidCameraTap.debug_sink) ---------------------

    def remember(self, camera_id: str, track_uuid: str, at: float, crop: Any) -> None:
        with self._lock:
            self._crops.pop(track_uuid, None)
            self._crops[track_uuid] = (camera_id, float(at), crop)
            while len(self._crops) > self._capacity:
                self._crops.popitem(last=False)

    # -- penangan kontrol -------------------------------------------------------

    @property
    def subscribed(self) -> bool:
        """Hanya untuk koneksi yang memintanya: backend baru tidak mewarisi langganan lama."""
        return self.enabled and self._subscribed_generation == self._api.generation

    def on_subscribe(self, message: Dict[str, Any]) -> Dict[str, Any]:
        ack = {"type": "ack", "v": 1, "ts": events.rfc3339(time.time()), "in_reply_to": "debug.subscribe"}
        if not self.enabled:
            return {**ack, "accepted": False, "reason": "debug mati di engine (debug.enabled: false)"}
        want = message.get("enabled") is True
        self._subscribed_generation = self._api.generation if want else None
        root = logging.getLogger()
        if want and self._handler not in root.handlers:
            root.addHandler(self._handler)
        elif not want and self._handler in root.handlers:
            root.removeHandler(self._handler)
        return {**ack, "accepted": True}

    def on_crop_list(self, message: Dict[str, Any]) -> Dict[str, Any]:
        refused = self._refuse(message, "debug.crop_list")
        if refused is not None:
            return refused
        with self._lock:
            entries = [(uuid, camera_id, at) for uuid, (camera_id, at, _crop) in self._crops.items()]
        crops = []
        for uuid, camera_id, at in reversed(entries):                 # terbaru dulu
            label = self._label_of(uuid) if self._label_of is not None else None
            crops.append({"track_uuid": uuid, "camera_id": camera_id, "at": at,
                          "person_id": label[0] if label else None,
                          "identity_source": label[1] if label else None})
        return {"type": "debug.crops", "v": 1, "ts": events.rfc3339(time.time()),
                "request_id": str(message.get("request_id")), "crops": crops}

    def on_crop_request(self, message: Dict[str, Any]) -> Dict[str, Any]:
        refused = self._refuse(message, "debug.crop_request")
        if refused is not None:
            return refused
        uuid = str(message.get("track_uuid"))
        reply: Dict[str, Any] = {"type": "debug.crop", "v": 1, "ts": events.rfc3339(time.time()),
                                 "request_id": str(message.get("request_id")), "track_uuid": uuid,
                                 "found": False}
        with self._lock:
            entry = self._crops.get(uuid)
        if entry is None:
            return reply
        camera_id, at, crop = entry
        import cv2

        ok, encoded = cv2.imencode(".jpg", crop, [int(cv2.IMWRITE_JPEG_QUALITY), _JPEG_QUALITY])
        if not ok:
            return reply
        height, width = crop.shape[:2]
        reply.update(found=True, camera_id=camera_id, at=at, width=int(width), height=int(height),
                     jpeg_b64=base64.b64encode(encoded.tobytes()).decode("ascii"))
        return reply

    def _refuse(self, message: Dict[str, Any], kind: str) -> Optional[Dict[str, Any]]:
        if self.subscribed and isinstance(message.get("request_id"), str):
            return None
        return {"type": "ack", "v": 1, "ts": events.rfc3339(time.time()), "in_reply_to": kind,
                "accepted": False, "reason": "debug belum dilanggan pada koneksi ini"}

    # -- log --------------------------------------------------------------------

    def forward_log(self, record: logging.LogRecord) -> None:
        if not self.subscribed:
            return
        self._api.emit_view({
            "type": "debug.log", "v": 1, "ts": events.rfc3339(record.created), "channel": "view",
            "level": record.levelname if record.levelname in ("WARNING", "ERROR", "CRITICAL") else "ERROR",
            "logger": record.name[:200], "message": record.getMessage()[:2000],
        })

    def close(self) -> None:
        logging.getLogger().removeHandler(self._handler)
        with self._lock:
            self._crops.clear()
