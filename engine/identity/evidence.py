"""Akumulator bukti: fusi embedding, bukan voting.

Pengganti `min_confirmations` yang di implementasi lama tidak menggerbangi apa
pun — ia hanya mengatur seberapa sering pengenalan diulang, sementara
identitas sudah terpasang sejak match pertama.

Kenapa dilebur, bukan divoting. Policy lama mengizinkan percobaan ulang tiap
0,1 detik, jadi dua "konfirmasi" datang dari dua gambar yang nyaris identik:
pose yang sama, blur yang sama, error yang berkorelasi penuh. Voting atas
sampel berkorelasi tidak menambah informasi apa pun — ia cuma mengulang
keyakinan yang sama dua kali dan menyebutnya dua bukti. Rata-rata berbobot
mutu meredam derau pose dan blur dengan cara yang voting tidak bisa.

Dan syarat konfirmasi wajib **tersebar dalam waktu**, bukan sekadar berjumlah
cukup. Tanpa itu, lima frame berturut-turut dari satu momen buruk tetap
meloloskan identitas yang salah.
"""

from __future__ import annotations

from collections import deque
from typing import Deque, List, Optional

import numpy as np

from .ports import Evidence

# Konstanta perseptual: berapa bukti, tersebar berapa detik, sebelum sebuah
# klaim boleh disebut terkonfirmasi. Keduanya tentang penglihatan.
DEFAULT_MIN_EVIDENCE = 3
DEFAULT_MIN_SPREAD_SECONDS = 0.5
DEFAULT_WINDOW = 5

# Di atas ambang ini, sebuah bukti baru praktis adalah salinan dari bukti yang
# sudah ada di jendela: pose yang sama, pencahayaan yang sama, error yang sama.
# Menerimanya menaikkan `evidence_count` tanpa menaikkan informasi, dan
# `evidence_count` itulah yang menggerbangi konfirmasi.
#
# Angkanya sengaja tinggi. Dua foto wajah orang yang sama dari detik yang
# berbeda wajar berada di 0,90-0,96; menolak di situ akan membuat track yang
# orangnya diam menghadap kamera tidak pernah mengumpulkan cukup bukti. Yang
# ditolak hanya yang benar-benar nyaris identik.
DEFAULT_REDUNDANCY_MAX = 0.985


class EvidenceWindow:
    """Jendela bukti terbatas untuk satu track."""

    def __init__(
        self,
        window: int = DEFAULT_WINDOW,
        min_evidence: int = DEFAULT_MIN_EVIDENCE,
        min_spread_seconds: float = DEFAULT_MIN_SPREAD_SECONDS,
        redundancy_max: float = DEFAULT_REDUNDANCY_MAX,
    ) -> None:
        if window < 1:
            raise ValueError("window minimal 1")
        self._items: Deque[Evidence] = deque(maxlen=window)
        self._min_evidence = min_evidence
        self._min_spread = min_spread_seconds
        self._redundancy_max = redundancy_max
        self._seen_total = 0
        self._rejected_redundant = 0

    def add(self, evidence: Evidence) -> bool:
        """Terima bukti baru. `False` berarti ditolak karena berlebihan.

        Sebaran waktu saja tidak cukup untuk menjamin bukti tidak berkorelasi
        — itu yang §9 butir 3 sebenarnya persoalkan. Dua frame berjarak satu
        detik dari orang yang duduk diam menghadap kamera punya pose, blur, dan
        pencahayaan yang sama persis; keduanya lolos syarat sebaran, tapi
        secara statistik mereka satu pengamatan yang dihitung dua kali. Dan
        `evidence_count` adalah yang menggerbangi konfirmasi, jadi menghitung
        salinan berarti melonggarkan gerbangnya tanpa ada yang memutuskan
        begitu.
        """
        vector = np.asarray(evidence.embedding, dtype=np.float32).reshape(-1)

        if self._items:
            existing = np.stack(
                [np.asarray(e.embedding, dtype=np.float32).reshape(-1) for e in self._items]
            )
            if float(np.max(existing @ vector)) > self._redundancy_max:
                self._rejected_redundant += 1
                return False

        self._items.append(evidence)
        self._seen_total += 1
        return True

    def clear(self) -> None:
        self._items.clear()

    def __len__(self) -> int:
        return len(self._items)

    @property
    def seen_total(self) -> int:
        """Berapa bukti yang pernah masuk, termasuk yang sudah keluar jendela."""
        return self._seen_total

    @property
    def rejected_redundant(self) -> int:
        """Berapa yang ditolak karena praktis salinan.

        Angka ini bukan hiasan: kalau ia jauh lebih besar dari `seen_total`,
        artinya pengenalan dijalankan jauh lebih sering daripada yang berguna,
        dan yang dibayar adalah GPU untuk menghasilkan jawaban yang sama
        berulang kali. Itu masukan langsung untuk menyetel penjadwalan.
        """
        return self._rejected_redundant

    @property
    def spread_seconds(self) -> float:
        if len(self._items) < 2:
            return 0.0
        return float(self._items[-1].pts - self._items[0].pts)

    @property
    def last_pts(self) -> Optional[float]:
        return self._items[-1].pts if self._items else None

    @property
    def is_confirmable(self) -> bool:
        """Cukup banyak DAN cukup tersebar.

        Dua syarat, bukan satu. Lima bukti dari satu detik yang sama secara
        statistik adalah satu bukti yang disalin lima kali.
        """
        return len(self._items) >= self._min_evidence and self.spread_seconds >= self._min_spread

    def fused(self) -> Optional[np.ndarray]:
        """Rata-rata berbobot mutu, dinormalisasi ulang.

        Vektor masuk sudah ter-L2-normalisasi, jadi rata-ratanya tidak lagi
        berada di bola satuan; normalisasi ulang wajib, kalau tidak skor
        cosine-nya mengecil sebanding dengan seberapa tidak sepakat bukti-
        buktinya — yang terlihat seperti kemiripan rendah padahal sebenarnya
        ketidaksepakatan internal.
        """
        if not self._items:
            return None

        vectors = np.stack([np.asarray(e.embedding, dtype=np.float32).reshape(-1) for e in self._items])
        weights = np.asarray([max(e.quality, 1e-6) for e in self._items], dtype=np.float32)

        mean = (vectors * weights[:, None]).sum(axis=0) / weights.sum()
        norm = float(np.linalg.norm(mean))
        return mean / norm if norm > 0 else mean

    def qualities(self) -> List[float]:
        return [e.quality for e in self._items]
