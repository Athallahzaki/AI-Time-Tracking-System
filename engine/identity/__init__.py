"""Lapisan identitas: siapa orang di track ini.

`engine/perception/` menjawab "ada orang yang sama bergerak di frame-frame
ini" — murni geometri, tanpa nama. Lapisan ini menjawab "orang itu 4471", dan
tidak pernah menjawab "4471 sedang istirahat": itu kebijakan, milik backend.

Strateginya mengikuti kenyataan pemasangan kamera di sudut ruangan: verifikasi
ulang berkala tidak bisa diandalkan karena kesempatan melihat wajah datang
jarang dan tidak bisa dijadwalkan. Jadi **tangkap momen langka yang bagus,
lalu pegang identitasnya lewat tracking** — dan buat "dipegang lewat tracking"
jadi keadaan yang punya nama dan kepercayaan yang meluruh, bukan sesuatu yang
diam-diam terlihat sama meyakinkannya dengan wajah yang baru dibaca.
"""

from .arbiter import Decision, IdentityArbiter, Outcome
from .evidence import EvidenceWindow
from .matcher import InMemoryReferenceStore, MatrixMatcher, VersionMismatch
from .ports import Evidence, IdentityState, Match, ReferenceStore, TrackIdentity

__all__ = [
    "Decision",
    "Evidence",
    "EvidenceWindow",
    "IdentityArbiter",
    "IdentityState",
    "InMemoryReferenceStore",
    "Match",
    "MatrixMatcher",
    "Outcome",
    "ReferenceStore",
    "TrackIdentity",
    "VersionMismatch",
]
