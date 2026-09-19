"""Satu-satunya permukaan engine ke luar.

Skema pesan, pembentukan event, penomoran urut, outbox, replay, dan server
socket NDJSON. Modul lain di `engine/` DILARANG menulis langsung ke socket dan
dilarang menyusun dict protokol sendiri — keduanya aturan yang sama dengan
alasan yang sama: kontrak yang ditegakkan di satu tempat bisa diuji, kontrak
yang diingat di sepuluh tempat tidak.
"""

from .events import (
    PROTOCOL_VERSION,
    ProtocolError,
    PtsClock,
    camera_coverage,
    camera_degraded,
    camera_failed,
    camera_online,
    engine_health,
    enrollment_needed,
    person_unidentified_present,
    presence_interval,
    rfc3339,
    snapshot,
    track_ended,
    track_heartbeat,
    track_identified,
    track_identity_changed,
    track_resumed,
    track_started,
    view_frame,
)
from .outbox import Outbox, SqliteOutbox
from .server import EngineApi

__all__ = [
    "EngineApi",
    "Outbox",
    "PROTOCOL_VERSION",
    "ProtocolError",
    "PtsClock",
    "SqliteOutbox",
    "camera_coverage",
    "camera_degraded",
    "camera_failed",
    "camera_online",
    "engine_health",
    "enrollment_needed",
    "person_unidentified_present",
    "presence_interval",
    "rfc3339",
    "snapshot",
    "track_ended",
    "track_heartbeat",
    "track_identified",
    "track_identity_changed",
    "track_resumed",
    "track_started",
    "view_frame",
]
