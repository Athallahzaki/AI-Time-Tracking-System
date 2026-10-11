"""ReID berjangkar wajah (dokumen 12 §3.6).

Logika di sini tetap tanpa model: embedding tubuh datang sebagai vektor numpy
lewat pesan antrean (`messages.py`). Model OSNet ONNX ada di
`embedder_onnx.py` dan gerbang kualitas crop di `quality.py`; keduanya hanya
dimuat bila `reid.enabled: true`. Perakitan ke kamera ada di `pipeline/`
(`reid_coordinator.py`, `reid_worker.py`, `reid_tap.py`, paket ea-r3), default mati.
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
