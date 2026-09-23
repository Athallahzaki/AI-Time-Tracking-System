"""SQLite storage for the backend.

Satu pintu koneksi (`connect()`): WAL, busy_timeout, foreign_keys, dan koneksi
yang benar-benar DITUTUP. Versi sebelumnya membuka koneksi baru per panggilan
tanpa WAL maupun busy_timeout, sementara thread receiver menulis per frame dan
thread API membaca — resep `database is locked`.

Kunci event durabel adalah `(outbox_id, seq)`, bukan `seq` saja: kalau engine
memulai penomoran ulang (outbox baru), `seq = 1` yang baru bukan duplikat dari
`seq = 1` yang lama.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

DB_PATH = Path(
    os.getenv(
        "BACKEND_DB_PATH",
        str(Path(__file__).resolve().parents[1] / "data" / "backend.db"),
    )
)

# Retensi data deteksi per frame (kanal view). Event durabel TIDAK ikut dipangkas.
DETECTION_RETENTION_DAYS = float(os.getenv("DETECTION_RETENTION_DAYS", "7"))

_init_lock = threading.Lock()
_initialized_for: Optional[str] = None


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    try:
        conn.execute("PRAGMA busy_timeout = 10000")
        conn.execute("PRAGMA foreign_keys = ON")
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def _parse_ts(value: Any) -> Optional[float]:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _columns(conn: sqlite3.Connection, table: str) -> List[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def init_database() -> None:
    """Idempotent. Cheap after the first call for the same DB_PATH."""
    global _initialized_for
    with _init_lock:
        if _initialized_for == str(DB_PATH) and DB_PATH.exists():
            return
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            _create_schema(conn)
        _initialized_for = str(DB_PATH)


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            type TEXT NOT NULL,
            payload TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            created_at REAL NOT NULL
        )
    """)

    # --- protocol_events: migrate the old `seq INTEGER PRIMARY KEY` layout ---
    existing = _columns(conn, "protocol_events")
    if existing and "outbox_id" not in existing:
        conn.execute("ALTER TABLE protocol_events RENAME TO protocol_events_legacy")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS protocol_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            outbox_id TEXT NOT NULL DEFAULT '',
            seq INTEGER NOT NULL,
            timestamp REAL NOT NULL,
            type TEXT NOT NULL,
            person_id TEXT,
            camera_id TEXT,
            start_ts REAL,
            end_ts REAL,
            payload TEXT NOT NULL,
            received_at REAL NOT NULL DEFAULT 0,
            UNIQUE(outbox_id, seq)
        )
    """)
    if "protocol_events_legacy" in {
        row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }:
        rows = conn.execute(
            "SELECT seq, timestamp, type, payload FROM protocol_events_legacy ORDER BY seq"
        ).fetchall()
        for seq, timestamp, event_type, payload in rows:
            _insert_protocol_event(conn, "", int(seq), float(timestamp), event_type,
                                   json.loads(payload))
        conn.execute("DROP TABLE protocol_events_legacy")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_protocol_type_person_time "
        "ON protocol_events(type, person_id, end_ts)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_protocol_timestamp ON protocol_events(timestamp)"
    )

    conn.execute("""
        CREATE TABLE IF NOT EXISTS dead_letters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            outbox_id TEXT NOT NULL DEFAULT '',
            seq INTEGER,
            received_at REAL NOT NULL,
            error TEXT NOT NULL,
            payload TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS enrollments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            person_id TEXT UNIQUE NOT NULL,
            enrollment_version INTEGER NOT NULL DEFAULT 1,
            reference_count INTEGER NOT NULL DEFAULT 0,
            enrolled_at REAL NOT NULL,
            last_seen_at REAL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS integration_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS corrections (
            correction_id TEXT PRIMARY KEY,
            created_at REAL NOT NULL,
            person_id TEXT,
            local_date TEXT,
            visit_id TEXT,
            adjustment_seconds REAL,
            exclude_visit INTEGER NOT NULL DEFAULT 0,
            payload TEXT NOT NULL
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_corrections_person_date "
        "ON corrections(person_id, local_date)"
    )
    conn.execute("""
        CREATE TABLE IF NOT EXISTS camera_overrides (
            camera_id TEXT PRIMARY KEY,
            enabled INTEGER,
            source_uri TEXT,
            updated_at REAL NOT NULL
        )
    """)

    # Normalized view-channel storage (display/forensics only, never billing).
    conn.execute("""
        CREATE TABLE IF NOT EXISTS detection_frames (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            camera_id TEXT NOT NULL,
            stream_epoch INTEGER NOT NULL,
            pts REAL NOT NULL,
            observed_at REAL NOT NULL,
            width INTEGER,
            height INTEGER,
            fps REAL,
            people_count INTEGER NOT NULL DEFAULT 0,
            UNIQUE(camera_id, stream_epoch, pts)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS track_observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            frame_id INTEGER NOT NULL REFERENCES detection_frames(id) ON DELETE CASCADE,
            camera_id TEXT NOT NULL,
            stream_epoch INTEGER NOT NULL,
            pts REAL NOT NULL,
            track_uuid TEXT NOT NULL,
            person_id TEXT,
            confidence REAL,
            x1 REAL NOT NULL,
            y1 REAL NOT NULL,
            x2 REAL NOT NULL,
            y2 REAL NOT NULL,
            session_elapsed REAL NOT NULL DEFAULT 0,
            presence_status TEXT,
            daily_used_seconds REAL NOT NULL DEFAULT 0,
            remaining_seconds REAL,
            UNIQUE(camera_id, stream_epoch, pts, track_uuid)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS track_sessions (
            camera_id TEXT NOT NULL,
            stream_epoch INTEGER NOT NULL,
            track_uuid TEXT NOT NULL,
            person_id TEXT,
            started_pts REAL NOT NULL,
            last_pts REAL NOT NULL,
            ended_pts REAL,
            first_observed_at REAL NOT NULL,
            last_observed_at REAL NOT NULL,
            session_elapsed REAL NOT NULL DEFAULT 0,
            presence_status TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY(camera_id, stream_epoch, track_uuid)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_observations_person_pts "
        "ON track_observations(person_id, pts)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sessions_person_active "
        "ON track_sessions(person_id, is_active)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_frames_observed ON detection_frames(observed_at)"
    )


# ---------------------------------------------------------------------------
# enrollments / employees
# ---------------------------------------------------------------------------

def upsert_enrollment(person_id: str, reference_count: int, enrollment_version: int) -> None:
    """Re-enrollment updates the row instead of hitting UNIQUE(person_id)."""
    init_database()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO enrollments (person_id, enrollment_version, reference_count, enrolled_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(person_id) DO UPDATE SET
                enrollment_version = excluded.enrollment_version,
                reference_count = excluded.reference_count,
                enrolled_at = excluded.enrolled_at
            """,
            (person_id, int(enrollment_version), int(reference_count), time.time()),
        )


def create_enrollment(person_id: str, reference_count: int) -> None:
    """Backward-compatible wrapper."""
    upsert_enrollment(person_id, reference_count, next_enrollment_version(person_id))


def next_enrollment_version(person_id: str) -> int:
    init_database()
    with connect() as conn:
        row = conn.execute(
            "SELECT enrollment_version FROM enrollments WHERE person_id = ?", (person_id,)
        ).fetchone()
    return int(row[0]) + 1 if row else 1


def get_enrollments() -> List[Dict[str, Any]]:
    init_database()
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT person_id, enrollment_version, reference_count, enrolled_at, last_seen_at
            FROM enrollments ORDER BY id ASC
            """
        ).fetchall()
    return [
        {
            "person_id": person_id,
            "enrollment_version": version,
            "reference_count": reference_count,
            "enrolled_at": enrolled_at,
            "last_seen_at": last_seen_at,
        }
        for person_id, version, reference_count, enrolled_at, last_seen_at in rows
    ]


def create_employee(employee_id: str, name: str) -> None:
    init_database()
    with connect() as conn:
        conn.execute(
            "INSERT INTO employees (employee_id, name, created_at) VALUES (?, ?, ?)",
            (employee_id, name, time.time()),
        )


def get_employees() -> List[Dict[str, Any]]:
    init_database()
    with connect() as conn:
        rows = conn.execute(
            "SELECT employee_id, name, created_at FROM employees ORDER BY id ASC"
        ).fetchall()
    return [
        {"employee_id": employee_id, "name": name, "created_at": created_at}
        for employee_id, name, created_at in rows
    ]


# ---------------------------------------------------------------------------
# generic event log (backend-side, e.g. non-durable engine messages)
# ---------------------------------------------------------------------------

def save_event(timestamp: float, event_type: str, payload: Dict[str, Any]) -> None:
    init_database()
    with connect() as conn:
        conn.execute(
            "INSERT INTO events (timestamp, type, payload) VALUES (?, ?, ?)",
            (timestamp, event_type, json.dumps(payload)),
        )


def get_events(limit: int = 50) -> List[Dict[str, Any]]:
    init_database()
    with connect() as conn:
        rows = conn.execute(
            "SELECT timestamp, type, payload FROM events ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        {"timestamp": timestamp, "type": event_type, "payload": json.loads(payload)}
        for timestamp, event_type, payload in reversed(rows)
    ]


# ---------------------------------------------------------------------------
# integration state
# ---------------------------------------------------------------------------

def set_integration_state(key: str, value: str) -> None:
    init_database()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO integration_state (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )


def get_integration_state(key: str, default: str = "") -> str:
    init_database()
    with connect() as conn:
        row = conn.execute(
            "SELECT value FROM integration_state WHERE key = ?", (key,)
        ).fetchone()
    return default if row is None else str(row[0])


def last_seq_key(outbox_id: str) -> str:
    return f"engine_last_event_seq:{outbox_id}" if outbox_id else "engine_last_event_seq"


# ---------------------------------------------------------------------------
# durable protocol events
# ---------------------------------------------------------------------------

def _insert_protocol_event(
    conn: sqlite3.Connection,
    outbox_id: str,
    seq: int,
    timestamp: float,
    event_type: str,
    payload: Dict[str, Any],
) -> bool:
    person_id = payload.get("person_id")
    if event_type == "track.identity_changed":
        person_id = payload.get("to_person_id")
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO protocol_events (
            outbox_id, seq, timestamp, type, person_id, camera_id,
            start_ts, end_ts, payload, received_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            outbox_id, int(seq), float(timestamp), event_type,
            str(person_id) if person_id is not None else None,
            payload.get("camera_id"),
            _parse_ts(payload.get("start_at")),
            _parse_ts(payload.get("end_at")),
            json.dumps(payload),
            time.time(),
        ),
    )
    return cursor.rowcount > 0


def save_protocol_event(
    timestamp: float,
    event_type: str,
    payload: Dict[str, Any],
    seq: int,
    outbox_id: str = "",
) -> bool:
    """Persist event and advance the per-outbox checkpoint in one transaction.

    Returns False when `(outbox_id, seq)` was already stored.
    """
    init_database()
    with connect() as conn:
        inserted = _insert_protocol_event(conn, outbox_id, seq, timestamp, event_type, payload)
        conn.execute(
            """
            INSERT INTO integration_state (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = CASE
                WHEN CAST(excluded.value AS INTEGER) > CAST(integration_state.value AS INTEGER)
                THEN excluded.value ELSE integration_state.value END
            """,
            (last_seq_key(outbox_id), str(int(seq))),
        )
    return inserted


def save_dead_letter(outbox_id: str, seq: Optional[int], error: str, payload: Dict[str, Any]) -> None:
    init_database()
    with connect() as conn:
        conn.execute(
            "INSERT INTO dead_letters (outbox_id, seq, received_at, error, payload) "
            "VALUES (?, ?, ?, ?, ?)",
            (outbox_id, seq, time.time(), error[:2000], json.dumps(payload, default=str)),
        )
        if seq is not None:
            conn.execute(
                """
                INSERT INTO integration_state (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = CASE
                    WHEN CAST(excluded.value AS INTEGER) > CAST(integration_state.value AS INTEGER)
                    THEN excluded.value ELSE integration_state.value END
                """,
                (last_seq_key(outbox_id), str(int(seq))),
            )


def get_dead_letters(limit: int = 100) -> List[Dict[str, Any]]:
    init_database()
    with connect() as conn:
        rows = conn.execute(
            "SELECT outbox_id, seq, received_at, error, payload FROM dead_letters "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        {"outbox_id": o, "seq": s, "received_at": r, "error": e, "payload": json.loads(p)}
        for o, s, r, e, p in rows
    ]


def get_protocol_events(
    event_type: Optional[str] = None,
    limit: Optional[int] = None,
    since_timestamp: Optional[float] = None,
    newest_first: bool = False,
) -> List[Dict[str, Any]]:
    init_database()
    query = "SELECT outbox_id, seq, timestamp, type, payload FROM protocol_events"
    clauses: List[str] = []
    params: List[Any] = []
    if event_type is not None:
        clauses.append("type = ?")
        params.append(event_type)
    if since_timestamp is not None:
        clauses.append("timestamp >= ?")
        params.append(float(since_timestamp))
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY id DESC" if newest_first else " ORDER BY id ASC"
    if limit is not None:
        query += " LIMIT ?"
        params.append(int(limit))
    with connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [
        {"outbox_id": o, "seq": seq, "timestamp": ts, "type": t, "payload": json.loads(p)}
        for o, seq, ts, t, p in rows
    ]


def get_presence_intervals(
    start_ts: float,
    end_ts: float,
    person_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Intervals overlapping [start_ts, end_ts), filtered in SQL (not `LIMIT 1000` oldest)."""
    init_database()
    query = (
        "SELECT payload FROM protocol_events WHERE type = 'presence.interval' "
        "AND person_id IS NOT NULL AND end_ts >= ? AND start_ts < ?"
    )
    params: List[Any] = [float(start_ts), float(end_ts)]
    if person_id is not None:
        query += " AND person_id = ?"
        params.append(str(person_id))
    query += " ORDER BY start_ts ASC"
    with connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [json.loads(row[0]) for row in rows]


def get_known_person_ids() -> List[str]:
    init_database()
    with connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT person_id FROM protocol_events WHERE type = 'presence.interval' "
            "AND person_id IS NOT NULL"
        ).fetchall()
    return [str(row[0]) for row in rows]


# ---------------------------------------------------------------------------
# corrections (append-only)
# ---------------------------------------------------------------------------

def save_correction(record: Dict[str, Any]) -> None:
    init_database()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO corrections (
                correction_id, created_at, person_id, local_date, visit_id,
                adjustment_seconds, exclude_visit, payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["correction_id"], time.time(), record.get("person_id"),
                record.get("date"), record.get("gap_id"),
                record.get("adjustment_seconds"),
                1 if record.get("exclude_visit") else 0,
                json.dumps(record),
            ),
        )


def get_corrections(
    person_id: Optional[str] = None,
    local_date: Optional[str] = None,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    init_database()
    query = "SELECT payload, created_at FROM corrections"
    clauses: List[str] = []
    params: List[Any] = []
    if person_id is not None:
        clauses.append("person_id = ?")
        params.append(person_id)
    if local_date is not None:
        clauses.append("local_date = ?")
        params.append(local_date)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(int(limit))
    with connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [{**json.loads(payload), "_created_at": created_at} for payload, created_at in rows]


# ---------------------------------------------------------------------------
# camera overrides (operator start/stop/source, persisted)
# ---------------------------------------------------------------------------

def get_camera_overrides() -> Dict[str, Dict[str, Any]]:
    init_database()
    with connect() as conn:
        rows = conn.execute(
            "SELECT camera_id, enabled, source_uri FROM camera_overrides"
        ).fetchall()
    result: Dict[str, Dict[str, Any]] = {}
    for camera_id, enabled, source_uri in rows:
        item: Dict[str, Any] = {}
        if enabled is not None:
            item["enabled"] = bool(enabled)
        if source_uri:
            item["source_uri"] = source_uri
        result[camera_id] = item
    return result


def set_camera_override(
    camera_id: str,
    enabled: Optional[bool] = None,
    source_uri: Optional[str] = None,
) -> None:
    init_database()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO camera_overrides (camera_id, enabled, source_uri, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(camera_id) DO UPDATE SET
                enabled = COALESCE(excluded.enabled, camera_overrides.enabled),
                source_uri = COALESCE(excluded.source_uri, camera_overrides.source_uri),
                updated_at = excluded.updated_at
            """,
            (
                camera_id,
                None if enabled is None else (1 if enabled else 0),
                source_uri,
                time.time(),
            ),
        )


# ---------------------------------------------------------------------------
# view-channel persistence (best-effort)
# ---------------------------------------------------------------------------

def save_detection_frame(message: Dict[str, Any], observed_at: float) -> bool:
    """Persist one enriched view.frame and its boxes atomically and idempotently."""
    camera_id = str(message.get("camera_id") or "")
    if not camera_id:
        raise ValueError("view.frame must contain camera_id")
    stream_epoch = int(message.get("stream_epoch") or 0)
    pts = float(message.get("pts") or 0.0)
    boxes = message.get("boxes") if isinstance(message.get("boxes"), list) else []

    init_database()
    with connect() as conn:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO detection_frames (
                camera_id, stream_epoch, pts, observed_at, width, height, fps, people_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                camera_id, stream_epoch, pts, float(observed_at),
                int(message.get("width") or 0), int(message.get("height") or 0),
                float(message.get("fps") or 0.0), len(boxes),
            ),
        )
        if cursor.rowcount == 0:
            return False
        frame_id = int(cursor.lastrowid)
        live_tracks: set[str] = set()

        for raw_box in boxes:
            if not isinstance(raw_box, dict):
                continue
            track_uuid = str(raw_box.get("track_uuid") or raw_box.get("track_id") or "")
            bbox = raw_box.get("bbox")
            if not track_uuid or not isinstance(bbox, list) or len(bbox) != 4:
                continue
            live_tracks.add(track_uuid)
            person_id = raw_box.get("person_id")
            person_text = str(person_id) if person_id is not None else None
            elapsed = max(0.0, float(raw_box.get("session_elapsed") or 0.0))
            status = raw_box.get("presence_status")
            conn.execute(
                """
                INSERT OR IGNORE INTO track_observations (
                    frame_id, camera_id, stream_epoch, pts, track_uuid, person_id,
                    confidence, x1, y1, x2, y2, session_elapsed, presence_status,
                    daily_used_seconds, remaining_seconds
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    frame_id, camera_id, stream_epoch, pts, track_uuid, person_text,
                    float(raw_box.get("confidence") or raw_box.get("similarity") or 0.0),
                    *(float(value) for value in bbox), elapsed, status,
                    float(raw_box.get("daily_used_seconds") or 0.0),
                    float(raw_box["remaining_seconds"])
                    if raw_box.get("remaining_seconds") is not None else None,
                ),
            )
            conn.execute(
                """
                INSERT INTO track_sessions (
                    camera_id, stream_epoch, track_uuid, person_id, started_pts,
                    last_pts, ended_pts, first_observed_at, last_observed_at,
                    session_elapsed, presence_status, is_active
                ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, 1)
                ON CONFLICT(camera_id, stream_epoch, track_uuid) DO UPDATE SET
                    person_id = COALESCE(excluded.person_id, track_sessions.person_id),
                    last_pts = MAX(track_sessions.last_pts, excluded.last_pts),
                    ended_pts = NULL,
                    last_observed_at = excluded.last_observed_at,
                    session_elapsed = MAX(track_sessions.session_elapsed, excluded.session_elapsed),
                    presence_status = excluded.presence_status,
                    is_active = 1
                """,
                (
                    camera_id, stream_epoch, track_uuid, person_text,
                    max(0.0, pts - elapsed), pts, observed_at, observed_at,
                    elapsed, status,
                ),
            )
            if person_text:
                conn.execute(
                    "UPDATE enrollments SET last_seen_at = ? WHERE person_id = ?",
                    (observed_at, person_text),
                )

        if live_tracks:
            placeholders = ",".join("?" for _ in live_tracks)
            conn.execute(
                f"""
                UPDATE track_sessions
                SET ended_pts = ?, last_observed_at = ?, is_active = 0
                WHERE camera_id = ? AND stream_epoch = ? AND is_active = 1
                  AND track_uuid NOT IN ({placeholders})
                """,
                (pts, observed_at, camera_id, stream_epoch, *sorted(live_tracks)),
            )
        else:
            conn.execute(
                """
                UPDATE track_sessions
                SET ended_pts = ?, last_observed_at = ?, is_active = 0
                WHERE camera_id = ? AND stream_epoch = ? AND is_active = 1
                """,
                (pts, observed_at, camera_id, stream_epoch),
            )
    return True


def prune_detection_history(retention_days: float = DETECTION_RETENTION_DAYS) -> int:
    """Delete view-channel rows older than the retention window. Returns frames removed."""
    if retention_days <= 0:
        return 0
    cutoff = time.time() - retention_days * 86400.0
    init_database()
    with connect() as conn:
        cursor = conn.execute("DELETE FROM detection_frames WHERE observed_at < ?", (cutoff,))
        removed = cursor.rowcount
        # ON DELETE CASCADE now actually fires (foreign_keys = ON).
        conn.execute(
            "DELETE FROM track_sessions WHERE is_active = 0 AND last_observed_at < ?",
            (cutoff,),
        )
    return removed


def get_detection_observations(
    camera_id: str | None = None,
    person_id: str | None = None,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    init_database()
    clauses: list[str] = []
    params: list[Any] = []
    if camera_id:
        clauses.append("camera_id = ?")
        params.append(camera_id)
    if person_id:
        clauses.append("person_id = ?")
        params.append(person_id)
    query = """SELECT camera_id, stream_epoch, pts, track_uuid, person_id,
                      confidence, x1, y1, x2, y2, session_elapsed,
                      presence_status, daily_used_seconds, remaining_seconds
               FROM track_observations"""
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(max(1, min(int(limit), 5000)))
    with connect() as conn:
        rows = conn.execute(query, params).fetchall()
    keys = ("camera_id", "stream_epoch", "pts", "track_uuid", "person_id",
            "confidence", "x1", "y1", "x2", "y2", "session_elapsed",
            "presence_status", "daily_used_seconds", "remaining_seconds")
    return [dict(zip(keys, row)) for row in reversed(rows)]
