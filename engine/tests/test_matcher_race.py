"""P4 overhaul: `match()` tidak boleh mencampur dua roster saat `rebuild()` berjalan.

Dua roster sengaja dibuat silang: vektor e0 milik P1 di roster pertama dan milik
Q2 di roster kedua. Matriks dari satu roster + nama dari roster lain menghasilkan
P2 atau Q1 dengan skor penuh, yaitu nama karyawan yang salah tanpa error apa pun.
"""

from __future__ import annotations

import sys
import threading

import numpy as np

from engine.identity import InMemoryReferenceStore, MatrixMatcher

E0 = np.eye(8, dtype=np.float32)[0]
E1 = np.eye(8, dtype=np.float32)[1]
ROSTER_A = {"P1": [E0], "P2": [E1]}
ROSTER_B = {"Q1": [E1], "Q2": [E0]}


class _RosterBergantian(InMemoryReferenceStore):
    def __init__(self) -> None:
        super().__init__(ROSTER_A)
        self._giliran = 0

    def references(self):
        self._giliran += 1
        return ROSTER_A if self._giliran % 2 else ROSTER_B


def test_match_tetap_konsisten_selama_rebuild_dari_thread_lain():
    matcher = MatrixMatcher(_RosterBergantian(), threshold=0.5, margin=0.1)
    berhenti = threading.Event()

    def bangun_ulang() -> None:
        while not berhenti.is_set():
            matcher.rebuild()

    lama = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)  # perbanyak perpindahan thread agar jendela race terbuka
    thread = threading.Thread(target=bangun_ulang, daemon=True)
    thread.start()
    try:
        salah = []
        for _ in range(20_000):
            hasil = matcher.match(E0)
            if hasil.person_id not in ("P1", "Q2"):
                salah.append(hasil.person_id)
        assert not salah, f"nama dari roster tercampur: {sorted(set(map(str, salah)))}"
    finally:
        berhenti.set()
        thread.join(timeout=5)
        sys.setswitchinterval(lama)


def test_snapshot_satu_roster_utuh():
    matcher = MatrixMatcher(InMemoryReferenceStore(ROSTER_A), threshold=0.5, margin=0.1)
    matrix, owners, people, version = matcher.snapshot()
    assert people == ["P1", "P2"] and matrix.shape == (2, 8)
    assert owners.tolist() == [0, 1] and version == matcher.embedding_version
    assert matcher.person_count == 2 and matcher.reference_count == 2
