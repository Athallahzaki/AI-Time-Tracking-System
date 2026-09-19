"""Validator kontrak engine <-> backend.

Dua lapis, sengaja dipisah:

- `schema_validator`  : apakah SATU pesan berbentuk benar.
- `conformance`       : apakah SEBUAH ALIRAN pesan menaati aturan yang tidak
                        bisa dinyatakan JSON Schema (urutan seq, siklus hidup
                        track, kamera putus, rantai interval, ruang pts).

Lapis kedua yang menangkap bug menarik. JSON Schema tidak pernah bisa tahu
bahwa `track.ended` setelah `camera.failed` seharusnya berbunyi `camera_lost`.
"""

from .schema_validator import (
    CHANNEL_OF,
    SchemaValidator,
    ValidationIssue,
    load_schema,
)
from .conformance import ConformanceChecker, ConformanceReport

__all__ = [
    "CHANNEL_OF",
    "SchemaValidator",
    "ValidationIssue",
    "load_schema",
    "ConformanceChecker",
    "ConformanceReport",
]
