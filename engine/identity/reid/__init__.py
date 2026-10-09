"""ReID berjangkar wajah (dokumen 12 §3.6).

Logika saja, tanpa model: embedding tubuh datang sebagai vektor numpy lewat
pesan antrean (`messages.py`). Belum dirakit ke `runtime/camera.py`; itu
menunggu penjadwal tahap 2 (EB).
"""

from .gallery import DailyGallery, PrototypeSet
from .merge import ReidConfig, TrackSpan, Verdict, check_group, check_pair, pick_best
from .messages import BodyObservation, TrackClosed, l2_normalize
from .pending import Assignment, PendingIdentities, PurgeReport, Resolution

__all__ = [
    "Assignment", "BodyObservation", "DailyGallery", "PendingIdentities",
    "PrototypeSet", "PurgeReport", "ReidConfig", "Resolution", "TrackClosed",
    "TrackSpan", "Verdict", "check_group", "check_pair", "l2_normalize", "pick_best",
]
