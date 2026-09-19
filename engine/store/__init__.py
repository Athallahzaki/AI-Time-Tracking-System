"""Penyimpanan lokal milik engine: vektor embedding dan gambar referensinya.

TIDAK ADA catatan kehadiran di sini. Sesi kerja, jam istirahat, dan riwayat
absensi milik backend, dan konsekuensi menyenangkan dari garis itu: engine
hampir sepenuhnya stateless. Kalau ia restart jam sebelas siang, yang hilang
cuma track yang sedang hidup — seluruh riwayat aman di backend. Kalau restart
engine berarti kehilangan data kehadiran, ada state yang salah tempat.
"""

from .references import (
    ReferenceRecord,
    RosterDiff,
    SqliteReferenceStore,
    StoreError,
)

__all__ = ["ReferenceRecord", "RosterDiff", "SqliteReferenceStore", "StoreError"]
