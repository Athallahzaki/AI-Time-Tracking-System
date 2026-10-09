"""Galeri tubuh harian multi-sudut, berjangkar wajah (dokumen 12 §3.6 butir 1–2).

Per orang disimpan beberapa prototipe embedding tubuh (depan, belakang,
samping) yang terkumpul sepanjang hari. Galeri HANYA diisi dari track yang
identitasnya berasal dari wajah; ReID tidak pernah menetapkan identitas
sendiri, jadi embedding dari track yang identitasnya hasil ReID ditolak di
pintu masuk, bukan dipercaya pemanggil.

Kenapa beberapa prototipe, bukan satu rata-rata: embedding tampak depan dan
tampak belakang orang yang sama bisa lebih jauh satu sama lain daripada tampak
depan dua orang berbeda berseragam sama. Rata-rata keduanya menghasilkan titik
yang tidak mirip siapa pun. Skor kecocokan adalah maksimum atas prototipe.

Akhir hari: `purge_day()` mengosongkan semuanya. Pakaian berganti antar hari,
dan galeri kemarin hanya menambah peluang tertukar.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

import numpy as np

from .messages import BodyObservation, l2_normalize

DEFAULT_CAPACITY = 12
# Di atas kemiripan ini embedding baru dianggap sudut yang sama dengan
# prototipe terdekat dan dilebur (rata-rata berbobot), bukan ditambah.
DEFAULT_MERGE_SIMILARITY = 0.95

_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class PrototypeSet:
    """Himpunan prototipe berkapasitas tetap yang menjaga keragaman sudut."""

    def __init__(self, capacity: int = DEFAULT_CAPACITY,
                 merge_similarity: float = DEFAULT_MERGE_SIMILARITY) -> None:
        if capacity < 1:
            raise ValueError("capacity minimal 1")
        self._capacity = capacity
        self._merge = merge_similarity
        self._vecs: List[np.ndarray] = []
        self._weights: List[int] = []

    def __len__(self) -> int:
        return len(self._vecs)

    def matrix(self) -> np.ndarray:
        if not self._vecs:
            return np.zeros((0, 0), dtype=np.float32)
        return np.stack(self._vecs)

    def add(self, embedding: np.ndarray) -> None:
        emb = l2_normalize(embedding)
        if not self._vecs:
            self._vecs.append(emb)
            self._weights.append(1)
            return
        mat = self.matrix()
        sims = mat @ emb
        nearest = int(np.argmax(sims))
        if sims[nearest] >= self._merge:
            self._fold(nearest, emb)
        elif len(self._vecs) < self._capacity:
            self._vecs.append(emb)
            self._weights.append(1)
        else:
            # Penuh: buang prototipe paling redundan HANYA bila yang baru lebih
            # menambah keragaman daripada yang dibuang; selain itu lebur.
            gram = mat @ mat.T
            np.fill_diagonal(gram, -np.inf)
            redundancy = gram.max(axis=1)
            victim = int(np.argmax(redundancy))
            if float(sims.max()) < float(redundancy[victim]):
                self._vecs[victim] = emb
                self._weights[victim] = 1
            else:
                self._fold(nearest, emb)

    def _fold(self, index: int, emb: np.ndarray) -> None:
        w = self._weights[index]
        merged = self._vecs[index] * w + emb
        self._vecs[index] = l2_normalize(merged)
        self._weights[index] = w + 1

    def score(self, embedding: np.ndarray) -> float:
        """Kemiripan kosinus maksimum terhadap prototipe; -1 bila kosong."""
        if not self._vecs:
            return -1.0
        return float((self.matrix() @ l2_normalize(embedding)).max())

    def score_set(self, other: "PrototypeSet") -> float:
        """Kemiripan maksimum antar dua himpunan prototipe."""
        if not self._vecs or not len(other):
            return -1.0
        return float((self.matrix() @ other.matrix().T).max())


class DailyGallery:
    """Galeri per `person_id` untuk satu hari kalender."""

    def __init__(self, day: str, capacity: int = DEFAULT_CAPACITY,
                 merge_similarity: float = DEFAULT_MERGE_SIMILARITY) -> None:
        self._day = _check_day(day)
        self._capacity = capacity
        self._merge = merge_similarity
        self._people: Dict[str, PrototypeSet] = {}
        self.rejected = 0  # embedding yang ditolak karena bukan berjangkar wajah
        # Orang yang dihapus (`forget_person`) hari ini: tidak diisi lagi sampai
        # purge harian, walau track yang masih memegang wajahnya terus mengirim.
        self._blocked: set = set()

    @property
    def day(self) -> str:
        return self._day

    def __contains__(self, person_id: object) -> bool:
        return person_id in self._people

    def __len__(self) -> int:
        return len(self._people)

    def persons(self) -> List[str]:
        return sorted(self._people)

    def prototype_count(self, person_id: str) -> int:
        protos = self._people.get(person_id)
        return len(protos) if protos is not None else 0

    def prototypes(self, person_id: str) -> Optional[PrototypeSet]:
        return self._people.get(person_id)

    def add(self, person_id: str, embedding: np.ndarray, *, source: str) -> bool:
        """Tambahkan embedding. Hanya `source="face"` yang diterima."""
        if source != "face":
            self.rejected += 1
            return False
        if person_id in self._blocked:
            return False
        protos = self._people.get(person_id)
        if protos is None:
            protos = self._people[person_id] = PrototypeSet(self._capacity, self._merge)
        protos.add(embedding)
        return True

    def add_observation(self, obs: BodyObservation) -> bool:
        """Isi dari pesan antrean: hanya bila track membawa identitas dari wajah."""
        if obs.embedding is None:
            return False
        if obs.face_person_id is None:
            self.rejected += 1
            return False
        return self.add(obs.face_person_id, obs.embedding, source="face")

    def scores(self, embedding: np.ndarray) -> List[Tuple[str, float]]:
        """(person_id, skor) terurut menurun."""
        emb = l2_normalize(embedding)
        out = [(pid, protos.score(emb)) for pid, protos in self._people.items()]
        out.sort(key=lambda item: item[1], reverse=True)
        return out

    def scores_set(self, protos: PrototypeSet) -> List[Tuple[str, float]]:
        """Seperti `scores`, untuk sekumpulan prototipe (kelompok ANON)."""
        out = [(pid, own.score_set(protos)) for pid, own in self._people.items()]
        out.sort(key=lambda item: item[1], reverse=True)
        return out

    def forget(self, person_id: str) -> int:
        """Hapus prototipe orang ini dan blokir sampai purge; kembalikan jumlah prototipe."""
        self._blocked.add(person_id)
        protos = self._people.pop(person_id, None)
        return len(protos) if protos is not None else 0

    def purge_day(self, new_day: Optional[str] = None) -> int:
        """Kosongkan galeri; kembalikan jumlah orang yang dibuang."""
        purged = len(self._people)
        self._people.clear()
        self._blocked.clear()
        self.rejected = 0
        if new_day is not None:
            self._day = _check_day(new_day)
        return purged


def _check_day(day: str) -> str:
    if not _DAY.match(day):
        raise ValueError(f"day harus YYYY-MM-DD, bukan {day!r}")
    return day

