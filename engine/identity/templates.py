"""Template wajah dari CCTV: gerbang tangkap, buffer kandidat, pasang dan cabut (ea-r31).

Masalahnya (docs/RENCANA-TEMPLATE-WAJAH.md): referensi enrollment adalah pas foto
frontal, sedangkan wajah CCTV kecil, miring, dan dari atas. Menambah referensi
dari kamera lokasi menutup jarak itu tanpa menyentuh bobot model. Matcher mengambil
skor maksimum per orang, jadi satu template salah sudah cukup untuk membajak:
seluruh modul ini ada untuk mencegah itu.

Pembagian peran:

- **Engine hanya mengusulkan.** `offer` dipanggil dari thread kamera untuk bukti
  wajah track CONFIRMED; yang lolos gerbang masuk buffer memori. `pull` menyerahkannya
  ke backend. Tidak ada referensi yang ditulis di jalur ini.
- **Backend memutuskan.** `apply` memasang yang dipilih backend sebagai referensi
  `source = learned`, setelah memeriksa ulang terhadap roster SAAT ITU: roster bisa
  berubah antara tangkap dan jadwal penerapan.
- **Jangkar tidak pernah disentuh.** Skor ke orangnya dihitung terhadap referensi
  enrollment saja (template tidak belajar dari template), dan `remove` hanya
  menghapus `source = learned`.
"""
from __future__ import annotations

import base64
import logging
import secrets
import threading
import time
from collections import deque
from typing import Any, Callable, Deque, Dict, List, Optional, Sequence, Tuple

import numpy as np

from .enrollment import _best_other

logger = logging.getLogger(__name__)

# Jeda singkat setelah bukti yang DITOLAK: menghemat kueri store untuk orang yang
# duduk lama di depan kamera, tanpa menunggu jeda penuh kandidat yang diterima.
REJECT_RETRY_SECONDS = 5.0


def _unit(vector: Any) -> np.ndarray:
    array = np.asarray(vector, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(array))
    return array / norm if norm > 0 else array


def encode_embedding(vector: np.ndarray) -> str:
    return base64.b64encode(np.asarray(vector, dtype="<f4").tobytes()).decode("ascii")


def decode_embedding(text: str, dimension: int) -> Optional[np.ndarray]:
    try:
        raw = base64.b64decode(text, validate=True)
    except (ValueError, TypeError):
        return None
    if len(raw) != dimension * 4:
        return None
    vector = np.frombuffer(raw, dtype="<f4").astype(np.float32)
    if not np.all(np.isfinite(vector)) or float(np.linalg.norm(vector)) <= 0:
        return None
    return _unit(vector)


def _encode_jpeg(image: np.ndarray) -> Optional[bytes]:
    try:
        import cv2
    except ImportError:  # pragma: no cover - cv2 selalu ada di runtime engine
        return None
    ok, buffer = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    return bytes(buffer) if ok else None


class FaceTemplateCollector:
    def __init__(self, config: Any, store: Any, matcher: Any,
                 clock: Callable[[], float] = time.time,
                 encode_jpeg: Callable[[np.ndarray], Optional[bytes]] = _encode_jpeg) -> None:
        self.config = config
        self._store = store
        self._matcher = matcher
        self._clock = clock
        self._encode_jpeg = encode_jpeg
        self._lock = threading.Lock()
        self._buffer: Deque[Dict[str, Any]] = deque(maxlen=int(config.buffer_size))
        self._next_allowed: Dict[str, float] = {}
        self.counters: Dict[str, int] = {"ditawarkan": 0, "diterima": 0, "dibuang_buffer_penuh": 0}

    # ---------------- tangkap (thread kamera) ----------------

    @property
    def min_anchor_similarity(self) -> float:
        value = self.config.min_anchor_similarity
        return float(value if value is not None else getattr(self._matcher, "_threshold", 0.4))

    def offer(self, person_id: str, camera_id: str, track_uuid: str, evidence: Any) -> Optional[str]:
        """Nilai satu bukti. -> None bila jadi kandidat, atau alasan penolakan."""
        now = self._clock()
        with self._lock:
            self.counters["ditawarkan"] += 1
            if now < self._next_allowed.get(person_id, 0.0):
                return self._count("jeda")
        reason, scores = self._judge(person_id, evidence)
        if reason is None:
            jpeg = self._encode_jpeg(evidence.face_crop)
            if not jpeg:
                reason = "gambar_rusak"
        with self._lock:
            if reason is not None:
                self._next_allowed[person_id] = now + min(REJECT_RETRY_SECONDS,
                                                          self.config.per_person_cooldown_seconds)
                return self._count(reason)
            self._next_allowed[person_id] = now + self.config.per_person_cooldown_seconds
            if len(self._buffer) == self._buffer.maxlen:
                self.counters["dibuang_buffer_penuh"] += 1
            self._buffer.append({
                "candidate_id": f"ft_{secrets.token_hex(8)}",
                "person_id": person_id,
                "camera_id": camera_id,
                "captured_at": _rfc3339(now),
                "track_uuid": track_uuid,
                "jpeg_b64": base64.b64encode(jpeg).decode("ascii"),
                "embedding_b64": encode_embedding(_unit(evidence.embedding)),
                "face_px": round(float(evidence.face_px), 1),
                "det_score": round(min(1.0, max(0.0, float(evidence.det_score))), 4),
                **({"yaw": round(float(evidence.yaw), 4)} if evidence.yaw is not None else {}),
                **scores,
            })
            self.counters["diterima"] += 1
        return None

    def _count(self, reason: str) -> str:
        key = f"tolak_{reason}"
        self.counters[key] = self.counters.get(key, 0) + 1
        return reason

    def _judge(self, person_id: str, evidence: Any) -> Tuple[Optional[str], Dict[str, Any]]:
        cfg = self.config
        if evidence.face_crop is None:
            return "tanpa_crop", {}
        if evidence.face_px < cfg.min_face_px:
            return "kecil", {}
        if evidence.det_score < cfg.min_det_score:
            return "skor_detektor", {}
        if evidence.yaw is None or evidence.yaw > cfg.max_yaw:
            return "menyamping", {}
        if evidence.embedding_version != self._store.embedding_version:
            return "versi_berbeda", {}
        return self.check(person_id, _unit(evidence.embedding))

    def check(self, person_id: str, query: np.ndarray) -> Tuple[Optional[str], Dict[str, Any]]:
        """Jangkar, margin, duplikat terhadap roster sekarang. Dipakai saat tangkap DAN saat pasang."""
        anchors = self._store.vectors_of(person_id, source="enroll")
        if anchors.shape[0] == 0:
            return "tanpa_jangkar", {}
        anchor = float(np.max(anchors @ query))
        rival_id, rival = _best_other(self._matcher, query, person_id)
        margin = anchor - rival if rival_id is not None else 2.0
        scores: Dict[str, Any] = {"anchor_similarity": round(max(-1.0, min(1.0, anchor)), 4),
                                  "margin": round(max(0.0, min(2.0, margin)), 4)}
        if rival_id is not None:
            scores["runner_up_id"] = rival_id
            scores["runner_up_similarity"] = round(max(-1.0, min(1.0, rival)), 4)
        if anchor < self.min_anchor_similarity:
            return "jangkar_rendah", scores
        if margin < self.config.min_margin:
            return "margin_tipis", scores
        own = self._store.vectors_of(person_id)
        if own.shape[0] and float(np.max(own @ query)) > self.config.duplicate_similarity:
            return "duplikat", scores
        return None, scores

    # ---------------- permintaan backend (thread API) ----------------

    def pull(self, max_items: int = 20) -> List[Dict[str, Any]]:
        with self._lock:
            items = []
            while self._buffer and len(items) < max(1, min(50, int(max_items))):
                items.append(self._buffer.popleft())
        return items

    def apply(self, items: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Pasang kandidat pilihan backend. Pemanggil memegang kunci emit engine."""
        results: List[Dict[str, Any]] = []
        written = 0
        for item in items:
            candidate_id = str(item.get("candidate_id", "?"))
            reason, reference_id = self._apply_one(item)
            entry: Dict[str, Any] = {"candidate_id": candidate_id, "accepted": reason is None}
            if reason is None:
                entry["reference_id"] = reference_id
                written += 1
            else:
                entry["reason"] = reason
            results.append(entry)
            # Item berikutnya diperiksa terhadap roster yang sudah memuat item ini:
            # dua kandidat kembar dalam satu batch tidak boleh sama-sama masuk.
            if reason is None and hasattr(self._matcher, "rebuild"):
                self._matcher.rebuild()
        logger.info("template.apply: %d dari %d dipasang", written, len(items))
        return results

    def _apply_one(self, item: Dict[str, Any]) -> Tuple[Optional[str], Optional[int]]:
        if item.get("embedding_version") != self._store.embedding_version:
            return "versi_berbeda", None
        query = decode_embedding(str(item.get("embedding_b64", "")), int(self._store.dimension))
        if query is None:
            return "embedding_rusak", None
        try:
            jpeg = base64.b64decode(str(item.get("jpeg_b64", "")), validate=True)
        except (ValueError, TypeError):
            return "gambar_rusak", None
        if not jpeg.startswith(b"\xff\xd8"):
            return "gambar_rusak", None
        person_id = str(item.get("person_id", ""))
        reason, scores = self.check(person_id, query)
        if reason is not None:
            return reason, None
        reference_id = self._store.add_reference(
            person_id=person_id, embedding=query, image_jpeg=jpeg,
            quality=float(max(0.0, min(1.0, scores.get("anchor_similarity", 0.0)))),
            enrollment_version=self._store.enrollment_version_of(person_id) or 1,
            camera_id=item.get("camera_id"), captured_at=item.get("captured_at"),
            source="learned",
        )
        return None, int(reference_id)

    def remove(self, reference_ids: Sequence[int]) -> int:
        removed = int(self._store.delete_learned(reference_ids))
        if removed and hasattr(self._matcher, "rebuild"):
            self._matcher.rebuild()
        logger.info("template.remove: %d template dicabut", removed)
        return removed

    def snapshot_counters(self) -> Dict[str, int]:
        with self._lock:
            return {**self.counters, "buffer": len(self._buffer)}


def _rfc3339(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(epoch)) + f".{int((epoch % 1) * 1000):03d}Z"
