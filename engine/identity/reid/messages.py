"""Pesan antrean per-kamera → inti identitas (dokumen 12 §3.6 dan §3.9).

Ini satu-satunya bentuk data yang diterima ReID. Kamera (dan kelak penjadwal
EB) cukup mengisi dataclass ini; ReID tidak pernah menyentuh frame, crop, atau
apa pun di `runtime/`. Karena itu modul ini sengaja hanya bergantung pada numpy:
batasnya harus bisa diuji tanpa model dan tanpa GPU.

Dua jenis pesan:

- `BodyObservation` — track terlihat. `embedding` boleh `None` (pembaruan murah
  untuk rentang hidup dan zona); embedding dihitung berbasis kejadian, bukan
  tiap frame (§3.6 butir 5).
- `TrackClosed` — track berakhir di kamera itu.

Waktu (`at`) adalah detik epoch UTC hasil konversi pts oleh engine, BUKAN jam
monotonic per proses: aturan cannot-link dan waktu tempuh membandingkan waktu
antar kamera, jadi semua kamera harus memakai sumbu waktu yang sama.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Optional

import numpy as np

# Sama dengan $defs.track_uuid di kontrak; ReID memancarkannya di identity.resolved.
_TRACK_UUID = re.compile(r"^tr_[A-Za-z0-9_-]{1,80}$")
# Sama dengan $defs.person_id; awalan ANON- dicadangkan untuk identitas tertunda.
_PERSON_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def l2_normalize(vector: np.ndarray) -> np.ndarray:
    """Salinan float32 1-D yang ter-L2-normalisasi. Menolak vektor nol/non-finit."""
    arr = np.asarray(vector, dtype=np.float32).reshape(-1)
    if arr.size == 0:
        raise ValueError("embedding kosong")
    if not np.all(np.isfinite(arr)):
        raise ValueError("embedding berisi NaN/inf")
    norm = float(np.linalg.norm(arr))
    if norm <= 1e-12:
        raise ValueError("embedding bernorma nol")
    return arr / norm


def _check_common(camera_id: str, track_uuid: str, at: float) -> None:
    if not camera_id:
        raise ValueError("camera_id wajib diisi")
    if not _TRACK_UUID.match(track_uuid):
        raise ValueError(f"track_uuid tidak sesuai kontrak (tr_...): {track_uuid!r}")
    if not isinstance(at, (int, float)) or not math.isfinite(at):
        raise ValueError(f"at harus detik epoch yang finit, bukan {at!r}")


@dataclass(frozen=True)
class BodyObservation:
    """Satu pengamatan track dari satu kamera.

    `track_id` adalah ID tracker per kamera (boleh didaur ulang); `track_uuid`
    unik seumur hidup dan dipakai sebagai kunci, karena itulah yang muncul di
    `identity.resolved.track_uuids`.

    `face_person_id` diisi HANYA bila identitas track saat ini berasal dari
    wajah (arbiter CONFIRMED/HELD dari wajah di track yang sama). Jangan pernah
    mengisinya dengan identitas hasil ReID: itulah jangkar galeri, dan jangkar
    yang diisi dari tebakan tubuh membuat galeri meracuni dirinya sendiri.

    `zone` adalah nama lokasi (luar, lobby, smoking, hiburan, biliar). Bila
    kosong, lokasi dianggap sama dengan `camera_id`.
    """

    camera_id: str
    track_id: int
    track_uuid: str
    at: float
    embedding: Optional[np.ndarray] = None
    face_person_id: Optional[str] = None
    zone: Optional[str] = None

    def __post_init__(self) -> None:
        _check_common(self.camera_id, self.track_uuid, self.at)
        if self.embedding is not None:
            object.__setattr__(self, "embedding", l2_normalize(self.embedding))
        if self.face_person_id is not None:
            if not _PERSON_ID.match(self.face_person_id):
                raise ValueError(f"face_person_id tidak valid: {self.face_person_id!r}")
            if self.face_person_id.upper().startswith("ANON-"):
                raise ValueError("face_person_id tidak boleh berawalan ANON-")

    @property
    def location(self) -> str:
        return self.zone or self.camera_id


@dataclass(frozen=True)
class TrackClosed:
    """Track berakhir. `at` = terakhir kali track benar-benar terlihat."""

    camera_id: str
    track_uuid: str
    at: float

    def __post_init__(self) -> None:
        _check_common(self.camera_id, self.track_uuid, self.at)
