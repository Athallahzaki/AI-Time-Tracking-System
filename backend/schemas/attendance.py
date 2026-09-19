"""Attendance-related API schemas.

These are the shapes that frontend sees. They are distinct from protocol
messages — the protocol describes what the engine emits, these describe what
the API returns to the browser.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


# ── Gap classification ───────────────────────────────────────────────────────

class GapClassification(str, Enum):
    """How a gap between two intervals was classified by the backend.

    This is the core business logic — see session_deriver.py and break_policy.py.
    """
    TRACKING_LOSS = "tracking_loss"    # False gap: end_zone=interior, short duration
    BREAK = "break"                    # Real break: person left via door
    DEPARTURE = "departure"            # Person left and didn't come back (long gap)
    CAMERA_FAILURE = "camera_failure"  # Camera died — not anyone's fault
    SYSTEM_EVENT = "system_event"      # Engine shutdown or similar
    OFFICIAL_BREAK = "official_break"  # Within official break hours (not counted)
    UNKNOWN = "unknown"                # Couldn't classify — needs manual review


class GapInfo(BaseModel):
    """A gap between two presence intervals, with classification."""
    gap_id: str
    person_id: str
    camera_id: str
    start_at: str   # RFC3339 — when the previous interval ended
    end_at: str     # RFC3339 — when the next interval started
    duration_seconds: float
    classification: GapClassification
    # Provenance from the interval that ended
    end_zone: str           # "door" | "interior" | "frame_edge"
    end_reason: str         # from EndReason enum
    end_source: str         # "face" | "tracking" | "forced"
    # Provenance from the interval that started
    start_zone: Optional[str] = None
    start_source: Optional[str] = None
    # Whether this gap was manually corrected
    corrected: bool = False
    correction_id: Optional[str] = None


# ── Presence intervals (raw from engine, stored in DB) ───────────────────────

class PresenceIntervalResponse(BaseModel):
    """A raw presence interval as stored in DB — faithful copy of engine output."""
    interval_id: str
    person_id: str
    camera_id: str
    start_at: str
    end_at: str
    duration_seconds: float
    start_source: str
    end_source: str
    start_zone: str
    end_zone: str
    end_reason: str
    identity_confidence: float = 0.0
    evidence_count: int = 0
    prev_interval_id: Optional[str] = None
    seq: int = 0


# ── Derived sessions ────────────────────────────────────────────────────────

class DerivedSession(BaseModel):
    """A session derived from chaining intervals and classifying gaps.

    This is what the frontend shows as "presence" for a person. Gaps classified
    as tracking_loss are absorbed into the session; gaps classified as break
    or departure create session boundaries.
    """
    session_id: str
    person_id: str
    camera_id: str
    start_at: str
    end_at: str
    duration_seconds: float
    # Constituent intervals
    interval_count: int
    interval_ids: List[str] = []
    # Gaps within this session that were classified as tracking_loss
    absorbed_gaps: List[GapInfo] = []
    # Whether any correction applies to this session
    has_corrections: bool = False
    # Status
    is_active: bool = False  # Still ongoing (no end yet)


# ── Break usage ──────────────────────────────────────────────────────────────

class BreakEntry(BaseModel):
    """A single break event — a gap classified as 'break'."""
    gap_id: str
    start_at: str
    end_at: str
    duration_seconds: float
    camera_id: str
    # How the gap ended — for UI to show whether this is suspicious
    end_zone: str
    end_reason: str
    # Correction info
    corrected: bool = False
    original_duration_seconds: Optional[float] = None


class BreakUsage(BaseModel):
    """Break usage summary for a person on a given date."""
    person_id: str
    date: str  # YYYY-MM-DD
    allowance_minutes: float
    used_minutes: float
    remaining_minutes: float
    break_count: int
    breaks: List[BreakEntry] = []
    # Suspicious gaps (end_zone=interior) that might be false breaks
    suspicious_gap_count: int = 0
    # Status
    status: str = "ok"  # "ok" | "warning" | "exceeded"


# ── Active sessions (real-time) ─────────────────────────────────────────────

class ActiveSession(BaseModel):
    """Currently active presence session (person is visible right now)."""
    track_uuid: str
    person_id: Optional[str] = None
    camera_id: str
    identity_source: Optional[str] = None  # "face" | "tracking"
    since: str  # RFC3339
    duration_seconds: float
    confidence: float = 0.0


# ── Summary / stats ─────────────────────────────────────────────────────────

class AttendanceSummary(BaseModel):
    """Aggregated attendance info for the dashboard."""
    total_present: int = 0
    total_identified: int = 0
    total_unidentified: int = 0
    total_on_break: int = 0
    cameras_online: int = 0
    cameras_failed: int = 0
    cameras_degraded: int = 0


class DashboardStats(BaseModel):
    """Stats for the dashboard StatsRow component (backward compat)."""
    activeFacilities: int = 0
    totalFacilities: int = 0
    activeUsers: int = 0
    totalUsage: str = "0s"
    avgSession: str = "0s"
    exceededDuration: int = 0


class AttendanceEvent(BaseModel):
    """An event in the attendance event log."""
    event_id: str
    timestamp: str
    event_type: str
    person_id: Optional[str] = None
    camera_id: Optional[str] = None
    details: dict = {}
