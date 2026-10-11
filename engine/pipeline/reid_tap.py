"""Sisi kamera ReID: dari track dan frame ke pesan antrean ReID (dokumen 12 §3.6).

Satu objek per kamera, dipanggil HANYA dari thread kamera itu (`runtime/camera.py`,
`_on_frame`). Tugasnya sempit:

1. Terapkan label dari koordinator (kotak masuk) ke perakit presence kamera ini:
   `ANON-xxxx` / karyawan lewat galeri (`reid`), karyawan lewat penyelesaian
   mundur (`reid_retro`), atau pencabutan. Track yang dipegang WAJAH tidak
   pernah dilabeli ReID: wajah selalu menang.
2. Tentukan kapan embedding dihitung — berbasis kejadian, bukan tiap frame:
   track baru muncul, identitas wajah baru terkonfirmasi, lalu paling sering
   sekali per `embed_interval_seconds`. Crop lolos gerbang kualitas dulu,
   disalin, lalu dititipkan ke worker (tidak pernah memblok).
3. Kirim pembaruan rentang hidup murah (tanpa embedding) sekitar sekali per
   detik, dan segera saat wajah baru terkonfirmasi, supaya aturan cannot-link
   dan waktu tempuh melihat rentang yang benar dan kelompok ANON diselesaikan
   tanpa menunggu embedding berikutnya.
4. Track yang hilang → `TrackClosed`.

Identitas wajah dibaca dari `track.attributes["identity_state"]` (arbiter).
Hanya itu yang boleh jadi `face_person_id`; label ReID di sini tidak pernah
dikirim balik sebagai jangkar (galeri yang meracuni dirinya sendiri).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Deque, Dict, Optional, Sequence, Tuple

from ..identity.reid import BodyObservation, TrackClosed
from ..identity.reid.quality import CropRules, assess_crop
from ..ports.tracking import TrackState
from .reid_coordinator import KIND_LABEL, KIND_RETRY

logger = logging.getLogger("engine.pipeline.reid_tap")

SPAN_UPDATE_SECONDS = 1.0
RETRY_SECONDS = 1.0
# identity_source arbiter yang berarti "identitas ini berasal dari wajah di track ini".
FACE_SOURCES = ("face", "tracking")

Submit = Callable[..., bool]


@dataclass
class _TrackState:
    track_id: int
    last_seen_at: float
    last_embed_at: Optional[float] = None
    face_embedded: Optional[str] = None   # identitas wajah saat embedding terakhir dititipkan
    face_observed: Optional[str] = None   # identitas wajah terakhir yang dikirim langsung
    last_span_at: float = float("-inf")
    retry_after: float = float("-inf")


@dataclass
class TapMetrics:
    submitted: int = 0
    rejected_full: int = 0
    gate_too_small: int = 0
    gate_aspect: int = 0
    gate_truncated: int = 0
    gate_empty: int = 0
    labels_applied: int = 0
    labels_cleared: int = 0

    def count_gate(self, reason: str) -> None:
        name = f"gate_{reason}"
        if hasattr(self, name):
            setattr(self, name, getattr(self, name) + 1)


def face_identity(track: Any) -> Optional[str]:
    identity = getattr(track, "attributes", {}).get("identity_state")
    person = getattr(identity, "person_id", None)
    source = getattr(identity, "identity_source", None)
    if person and source in FACE_SOURCES:
        return str(person)
    return None


class ReidCameraTap:
    def __init__(self, camera_id: str, coordinator: Any, submit: Submit,
                 clock_for: Callable[[str], Any], assembler: Any, rules: CropRules,
                 embed_interval_seconds: float,
                 span_update_seconds: float = SPAN_UPDATE_SECONDS,
                 retry_seconds: float = RETRY_SECONDS) -> None:
        self.camera_id = camera_id
        self._coordinator = coordinator
        self._inbox: Deque = coordinator.register(camera_id)
        self._submit = submit
        self._clock_for = clock_for
        self._assembler = assembler
        self._rules = rules
        self._interval = float(embed_interval_seconds)
        self._span_every = float(span_update_seconds)
        self._retry = float(retry_seconds)
        self._state: Dict[str, _TrackState] = {}
        self._labels: Dict[str, Tuple[str, str]] = {}
        self.metrics = TapMetrics()

    # -- dibaca camera.py -------------------------------------------------------

    def label_of(self, track_uuid: str) -> Optional[Tuple[str, str]]:
        """(person_id, identity_source) dari ReID, atau None."""
        return self._labels.get(track_uuid)

    # -- per frame --------------------------------------------------------------

    def step(self, frame: Any, tracks: Sequence[Any], pts: float) -> None:
        at = float(self._clock_for(self.camera_id).offset) + float(pts)
        self._drain()
        image = getattr(frame, "image", None)
        active = set()
        for track in tracks:
            if track.state not in (TrackState.NEW, TrackState.TRACKED):
                continue
            uuid = track.attributes.get("track_uuid")
            if not uuid:
                continue
            active.add(uuid)
            self._observe_track(track, uuid, at, image)
        for uuid in [u for u in self._state if u not in active]:
            self._end(uuid)

    def close_all(self) -> None:
        """Kamera berhenti/putus/reconnect: semua track kamera ini berakhir."""
        for uuid in list(self._state):
            self._end(uuid)
        self._labels.clear()

    # -- internal ---------------------------------------------------------------

    def _observe_track(self, track: Any, uuid: str, at: float, image: Any) -> None:
        state = self._state.get(uuid)
        if state is None:
            state = self._state[uuid] = _TrackState(int(getattr(track, "track_id", -1)), at)
        state.last_seen_at = at
        face = face_identity(track)
        if face is not None and uuid in self._labels:
            # Wajah menang; assembler sudah ditimpa oleh `identified`.
            self._labels.pop(uuid, None)

        due = (state.last_embed_at is None or face != state.face_embedded
               or at - state.last_embed_at >= self._interval)
        if due and at >= state.retry_after and image is not None:
            self._try_embed(track, uuid, state, at, face, image)

        if face != state.face_observed or at - state.last_span_at >= self._span_every:
            state.face_observed = face
            state.last_span_at = at
            self._coordinator.observe(BodyObservation(
                camera_id=self.camera_id, track_id=state.track_id, track_uuid=uuid,
                at=at, embedding=None, face_person_id=face,
            ))

    def _try_embed(self, track: Any, uuid: str, state: _TrackState, at: float,
                   face: Optional[str], image: Any) -> None:
        height, width = image.shape[:2]
        box = track.bbox
        quality = assess_crop(float(box.x1), float(box.y1), float(box.x2), float(box.y2),
                              width, height, self._rules)
        if not quality.usable:
            self.metrics.count_gate(quality.reason)
            state.retry_after = at + self._retry
            return
        x1, y1, x2, y2 = quality.box
        crop = image[y1:y2, x1:x2].copy()
        if self._submit(self.camera_id, state.track_id, uuid, at, crop,
                        face_person_id=face, zone=None):
            self.metrics.submitted += 1
            state.last_embed_at = at
            state.face_embedded = face
        else:
            self.metrics.rejected_full += 1
            state.retry_after = at + self._retry

    def _end(self, uuid: str) -> None:
        state = self._state.pop(uuid, None)
        self._labels.pop(uuid, None)
        if state is None:
            return
        self._coordinator.close(TrackClosed(self.camera_id, uuid, state.last_seen_at))

    def _drain(self) -> None:
        while True:
            try:
                kind, uuid, person_id, source = self._inbox.popleft()
            except IndexError:
                return
            state = self._state.get(uuid)
            if state is None:
                continue  # track sudah berakhir di kamera ini
            if kind == KIND_RETRY:
                # Crop dibuang worker (basi/gagal): titipkan lagi di frame berikutnya.
                state.last_embed_at = None
                continue
            if kind != KIND_LABEL:
                continue
            if state.face_observed is not None:
                continue  # wajah menang
            if person_id is None or source in (None, "face", "tracking"):
                if self._labels.pop(uuid, None) is not None:
                    self._assembler.reid_cleared(uuid)
                    self.metrics.labels_cleared += 1
                continue
            if self._labels.get(uuid) == (person_id, source):
                continue
            if self._assembler.reid_assigned(uuid, person_id):
                self._labels[uuid] = (person_id, source)
                self.metrics.labels_applied += 1
