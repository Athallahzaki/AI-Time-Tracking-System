"""Klaim wajah lintas kamera (overhaul P8 bagian 1).

Arbiter bekerja per kamera dan hanya mencegah dua track di SATU kamera memegang
orang yang sama. Registry ini dibagi semua arbiter dan menjawab pertanyaan yang
tidak bisa dijawab satu kamera: bolehkah orang ini dipegang di dua kamera
sekaligus?

Aturan (keputusan tim, 3 Nov 2026):

- Dua kamera yang bidang pandangnya bertumpang-tindih (dideklarasikan di config)
  boleh memegang orang yang sama bersamaan. Kamera kedua menjadi bukti penguat,
  bukan tabrakan (`corroborated`).
- Selain itu, satu orang di dua tempat sekaligus mustahil: skor wajah tertinggi
  menang. Seri = pemegang lama menang. Yang kalah kembali tidak dikenal, tidak
  dipindah ke nama lain.
- Pemenang tidak menyentuh arbiter kamera lain (thread lain). Pemegang yang
  kalah dicatat di sini dan dilepas oleh arbiter kameranya sendiri pada `tick`
  berikutnya.

shortcut: hanya klaim yang hidup BERSAMAAN yang diperiksa. Klaim berurutan yang
melanggar waktu tempuh tidak dicek, karena arbiter memakai PTS per kamera dan
tidak punya jam bersama. Naikkan bila log menunjukkan wajah sah berpindah kamera
lebih cepat dari mungkin.
"""

from __future__ import annotations

import threading
from typing import Dict, FrozenSet, Iterable, Set, Tuple


class CrossCameraClaims:
    def __init__(self, overlapping_cameras: Iterable[Iterable[str]] = ()) -> None:
        overlap: Set[FrozenSet[str]] = set()
        for pair in overlapping_cameras:
            cameras = frozenset(str(c) for c in pair)
            if len(cameras) != 2:
                raise ValueError(f"pasangan kamera tumpang-tindih harus 2 kamera berbeda: {list(pair)!r}")
            overlap.add(cameras)
        self._overlap = frozenset(overlap)
        self._lock = threading.Lock()
        # person_id -> camera_id -> (track_uuid, similarity)
        self._holders: Dict[str, Dict[str, Tuple[str, float]]] = {}
        self._evicted: Set[str] = set()
        self.corroborated = 0
        self.evicted_total = 0
        self.rejected = 0

    def overlaps(self, camera_a: str, camera_b: str) -> bool:
        return frozenset((camera_a, camera_b)) in self._overlap

    def claim(self, camera_id: str, track_uuid: str, person_id: str, similarity: float) -> bool:
        """True = klaim boleh dipasang. Pemegang mustahil yang lebih lemah ditandai untuk dilepas."""
        with self._lock:
            holders = self._holders.setdefault(person_id, {})
            conflicts = [(camera, held) for camera, held in holders.items()
                         if camera != camera_id and not self.overlaps(camera, camera_id)]
            if any(held_similarity >= similarity for _, (_, held_similarity) in conflicts):
                self.rejected += 1
                return False
            for camera, (uuid, _) in conflicts:
                del holders[camera]
                self._evicted.add(uuid)
                self.evicted_total += 1
            if any(camera != camera_id for camera in holders):
                self.corroborated += 1
            holders[camera_id] = (track_uuid, float(similarity))
            return True

    def refresh(self, camera_id: str, track_uuid: str, person_id: str, similarity: float) -> None:
        """Perbarui skor klaim yang MASIH dipegang track ini; tidak pernah menghidupkan klaim yang dicabut."""
        with self._lock:
            holders = self._holders.get(person_id)
            if holders and holders.get(camera_id, ("",))[0] == track_uuid:
                holders[camera_id] = (track_uuid, float(similarity))

    def release(self, camera_id: str, track_uuid: str, person_id: str) -> None:
        with self._lock:
            self._evicted.discard(track_uuid)
            holders = self._holders.get(person_id)
            if holders and holders.get(camera_id, ("",))[0] == track_uuid:
                del holders[camera_id]
                if not holders:
                    del self._holders[person_id]

    def transfer(self, camera_id: str, old_uuid: str, new_uuid: str, person_id: str) -> None:
        """Track disambung (`adopt`): klaimnya pindah ke uuid baru di kamera yang sama."""
        with self._lock:
            holders = self._holders.get(person_id)
            if holders and holders.get(camera_id, ("",))[0] == old_uuid:
                holders[camera_id] = (new_uuid, holders[camera_id][1])

    def take_evicted(self, track_uuids: Iterable[str]) -> Set[str]:
        """Track milik pemanggil yang kalah klaim; dikeluarkan dari daftar tunggu."""
        with self._lock:
            mine = self._evicted.intersection(track_uuids)
            self._evicted -= mine
            return mine

    def metrics(self) -> Dict[str, int]:
        with self._lock:
            return {"cross_corroborated": self.corroborated, "cross_evicted": self.evicted_total,
                    "cross_rejected": self.rejected}
