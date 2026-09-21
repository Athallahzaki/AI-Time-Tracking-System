"""Kosakata lapisan identitas.

Dipisah dari implementasinya karena tiga modul di bawah saling memakai tipe
yang sama, dan karena `engine/perception/` tidak boleh tahu apa pun dari sini —
batasnya persis di `Evidence`: perception menyerahkan crop wajah yang sudah
ter-align beserta skor mutunya, identity yang memutuskan itu siapa.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Protocol, Sequence

import numpy as np


class IdentityState(str, enum.Enum):
    """Keadaan klaim identitas sebuah track.

    `HELD` adalah yang paling lama ditempati di ruangan berkamera sudut, dan
    satu-satunya yang mencegah banjir celah palsu: orang yang membelakangi
    kamera tetap punya identitas, hanya dengan keandalan yang berbeda. Backend
    wajib bisa membedakannya dari identitas yang baru saja dibaca dari wajah,
    dan itulah kenapa ia state tersendiri, bukan flag.
    """

    PENDING = "PENDING"          # Track baru, belum ada bukti sama sekali
    PROVISIONAL = "PROVISIONAL"  # Ada match, tapi belum memenuhi syarat konfirmasi
    CONFIRMED = "CONFIRMED"      # Cukup bukti, tersebar cukup lama, lolos margin
    HELD = "HELD"                # Pernah confirmed; wajah tidak lagi terlihat
    EXPIRED = "EXPIRED"          # TTL habis; perlu verifikasi ulang


@dataclass(frozen=True)
class Evidence:
    """Satu pengamatan wajah yang layak dipakai.

    `embedding` sudah ter-L2-normalisasi. `quality` dipakai sebagai bobot saat
    peleburan, bukan sebagai gerbang — penggerbangan mutu terjadi lebih awal,
    di perception, sebelum biaya embed dibayar.
    """

    embedding: np.ndarray
    pts: float
    quality: float = 1.0
    embedding_version: str = "unknown"


@dataclass(frozen=True)
class Match:
    """Hasil pencocokan satu vektor gabungan terhadap seluruh roster.

    `margin` dihitung antar ORANG, bukan antar vektor referensi. Kandidat kedua
    yang berupa foto lain dari orang yang sama bukan kandidat; ia bukti
    tambahan. Lihat `matcher.py`.
    """

    person_id: Optional[str]
    similarity: float
    margin: float
    runner_up_id: Optional[str] = None
    runner_up_similarity: float = -1.0
    rejected_because: Optional[str] = None  # below_threshold | margin_too_narrow | empty_roster

    @property
    def is_match(self) -> bool:
        return self.person_id is not None


@dataclass
class TrackIdentity:
    """Klaim identitas satu track, beserta riwayat yang membuatnya bisa dicabut."""

    track_uuid: str
    camera_id: str
    state: IdentityState = IdentityState.PENDING
    person_id: Optional[str] = None
    confidence: float = 0.0
    similarity: float = 0.0
    margin: float = 0.0
    evidence_count: int = 0
    confirmed_at_pts: Optional[float] = None
    last_face_pts: Optional[float] = None
    disagreements: int = 0
    disagreeing_with: Optional[str] = None
    history: List[str] = field(default_factory=list)

    @property
    def has_identity(self) -> bool:
        return self.person_id is not None and self.state in {
            IdentityState.CONFIRMED,
            IdentityState.HELD,
            IdentityState.EXPIRED,
        }

    @property
    def identity_source(self) -> Optional[str]:
        """Apa yang sedang memegang identitas ini: wajah, atau tracker saja."""
        if not self.has_identity:
            return None
        return "face" if self.state is IdentityState.CONFIRMED else "tracking"


class ReferenceStore(Protocol):
    """Sumber vektor referensi. Implementasinya milik `engine/store/`."""

    @property
    def embedding_version(self) -> str:
        ...

    def references(self) -> Dict[str, Sequence[np.ndarray]]:
        """Vektor per `person_id`, semuanya sudah ter-L2-normalisasi."""
        ...
