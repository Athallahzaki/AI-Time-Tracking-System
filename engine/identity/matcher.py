"""Pencocokan matriks dengan uji margin.

Dua hal yang diperbaiki dari implementasi sebelumnya, dan keduanya bug
kebenaran, bukan optimisasi.

**Skor direduksi per ORANG sebelum diperingkat.** Versi lama mengambil `best`
dengan mengiterasi setiap vektor referensi, lalu membandingkan skor tertinggi
dengan threshold. Dua akibatnya. Pertama, karyawan dengan lima foto referensi
punya lima undian melawan karyawan dengan tiga — roster yang tidak seimbang
bias secara sistematis ke yang fotonya banyak. Kedua, dan ini yang mematikan:
siapa pun yang menambahkan uji margin di atasnya akan menemukan kandidat kedua
hampir selalu berupa **foto lain milik orang yang sama**, margin-nya mendekati
nol, dan seluruh roster ditolak. Foto kedua dari orang yang sama bukan
kandidat saingan; ia bukti tambahan.

**Versi embedding dicocokkan, bukan diasumsikan.** Vektor dari dua model hidup
di ruang berbeda; cosine antara keduanya bukan angka yang salah, ia angka yang
tidak punya arti apa pun. Tanpa pemeriksaan ini, mengganti embedder membuat
akurasi jatuh ke tingkat acak tanpa satu pun error.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from .ports import Match, ReferenceStore

# Ambang perseptual. Tidak satu pun dari ini boleh berubah karena alasan
# kebijakan kantor; semuanya tentang penglihatan.
DEFAULT_THRESHOLD = 0.37
DEFAULT_MARGIN = 0.06


class VersionMismatch(RuntimeError):
    """Query dan referensi berasal dari ruang vektor yang berbeda."""


class MatrixMatcher:
    """Satu GEMV menggantikan ribuan iterasi interpreter.

    Matriks `(M, 512)` dibangun ulang hanya saat roster berubah, jadi biaya
    penyusunannya dibayar sekali per `set_roster`, bukan per frame.
    """

    def __init__(
        self,
        store: ReferenceStore,
        threshold: float = DEFAULT_THRESHOLD,
        margin: float = DEFAULT_MARGIN,
    ) -> None:
        if not -1.0 <= threshold <= 1.0:
            raise ValueError(f"threshold di luar [-1, 1]: {threshold}")
        if margin < 0.0:
            raise ValueError(f"margin tidak boleh negatif: {margin}")

        self._store = store
        self._threshold = float(threshold)
        self._margin = float(margin)

        self._matrix: Optional[np.ndarray] = None
        self._owner_index: np.ndarray = np.empty(0, dtype=np.int32)
        self._people: List[str] = []
        self._version: str = store.embedding_version
        self.rebuild()

    # ---------------- roster ----------------

    def rebuild(self) -> None:
        """Susun ulang matriks dari store. Dipanggil saat roster berubah."""
        references = self._store.references()
        self._version = self._store.embedding_version

        rows: List[np.ndarray] = []
        owners: List[int] = []
        people: List[str] = []

        for person_id, vectors in sorted(references.items()):
            usable = [np.asarray(v, dtype=np.float32).reshape(-1) for v in vectors if v is not None]
            if not usable:
                continue
            index = len(people)
            people.append(person_id)
            for vector in usable:
                rows.append(_normalize(vector))
                owners.append(index)

        self._matrix = np.stack(rows, axis=0) if rows else None
        self._owner_index = np.asarray(owners, dtype=np.int32)
        self._people = people

    @property
    def person_count(self) -> int:
        return len(self._people)

    @property
    def reference_count(self) -> int:
        return 0 if self._matrix is None else int(self._matrix.shape[0])

    @property
    def embedding_version(self) -> str:
        return self._version

    # ---------------- pencocokan ----------------

    def match(self, query: np.ndarray, query_version: Optional[str] = None) -> Match:
        if query_version is not None and query_version != self._version:
            raise VersionMismatch(
                f"query `{query_version}` vs referensi `{self._version}`. Menolak mencocokkan: "
                "cosine antar dua ruang vektor bukan angka yang salah, ia angka tanpa arti."
            )

        if self._matrix is None:
            return Match(None, -1.0, 0.0, rejected_because="empty_roster")

        similarities = self._matrix @ _normalize(np.asarray(query, dtype=np.float32).reshape(-1))

        # Reduksi per orang SEBELUM peringkat. Inti perbaikannya ada di dua
        # baris ini: `np.maximum.at` mengambil skor terbaik tiap orang, dan
        # sisanya membandingkan antar orang, bukan antar foto.
        per_person = np.full(len(self._people), -1.0, dtype=np.float32)
        np.maximum.at(per_person, self._owner_index, similarities)

        best_index = int(np.argmax(per_person))
        best = float(per_person[best_index])
        best_id = self._people[best_index]

        runner_up_id: Optional[str] = None
        runner_up = -1.0
        if len(self._people) > 1:
            masked = per_person.copy()
            masked[best_index] = -np.inf
            runner_index = int(np.argmax(masked))
            runner_up = float(masked[runner_index])
            runner_up_id = self._people[runner_index]

        margin = best - runner_up if runner_up_id is not None else best + 1.0

        if best < self._threshold:
            return Match(None, best, margin, runner_up_id, runner_up, "below_threshold")

        # Threshold cuma bertanya "cukup mirip?". Tanpa pertanyaan kedua --
        # "mirip siapa lagi?" -- orang asing yang menyerupai dua karyawan akan
        # diberikan ke salah satunya dengan percaya diri, dan risikonya naik
        # seiring roster bertambah.
        if margin < self._margin:
            return Match(None, best, margin, runner_up_id, runner_up, "margin_too_narrow")

        return Match(best_id, best, margin, runner_up_id, runner_up)


def _normalize(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm > 0 else vector


class InMemoryReferenceStore:
    """Store sederhana untuk tes dan untuk roster kecil.

    Dua ratus karyawan x lima referensi x 512 float32 sekitar 2 MB. Di skala
    ini brute-force numpy selesai dalam mikrodetik, dan vector database justru
    lebih lambat karena overhead index -- sambil menambah satu layanan yang
    harus dioperasikan, dimonitor, dan di-backup.
    """

    def __init__(self, references: Dict[str, Sequence[np.ndarray]], embedding_version: str = "test-v1") -> None:
        self._references = {k: list(v) for k, v in references.items()}
        self._version = embedding_version

    @property
    def embedding_version(self) -> str:
        return self._version

    def references(self) -> Dict[str, Sequence[np.ndarray]]:
        return self._references

    def set(self, person_id: str, vectors: Sequence[np.ndarray]) -> None:
        self._references[person_id] = list(vectors)

    def drop(self, person_id: str) -> None:
        self._references.pop(person_id, None)
