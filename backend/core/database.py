from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List
import time

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "backend.db"


def init_database() -> None:
    DB_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                type TEXT NOT NULL,
                payload TEXT NOT NULL
            )
            """
        )
        
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS employees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )

        conn.execute("""
            CREATE TABLE IF NOT EXISTS protocol_events (
                seq INTEGER PRIMARY KEY,
                timestamp REAL NOT NULL,
                type TEXT NOT NULL,
                payload TEXT NOT NULL
            )
        """)
        
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS enrollments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                person_id TEXT UNIQUE NOT NULL,
                enrollment_version INTEGER NOT NULL DEFAULT 1,
                reference_count INTEGER NOT NULL DEFAULT 0,
                enrolled_at REAL NOT NULL,
                last_seen_at REAL
            )
            """
        )

        conn.execute("""
            CREATE TABLE IF NOT EXISTS integration_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS free_time_usage (
                person_id TEXT NOT NULL,
                local_date TEXT NOT NULL,
                used_seconds REAL NOT NULL DEFAULT 0,
                updated_at REAL NOT NULL,
                PRIMARY KEY (person_id, local_date)
            )
        """)

        # Normalized view-channel storage. protocol_events remains the durable
        # event log; these tables make detector output queryable without
        # unpacking JSON and survive frontend refresh/reconnect.
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

        conn.commit()


def get_free_time_usage() -> Dict[tuple[str, str], float]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS free_time_usage (
                person_id TEXT NOT NULL,
                local_date TEXT NOT NULL,
                used_seconds REAL NOT NULL DEFAULT 0,
                updated_at REAL NOT NULL,
                PRIMARY KEY (person_id, local_date)
            )
        """)
        rows = conn.execute(
            "SELECT person_id, local_date, used_seconds FROM free_time_usage"
        ).fetchall()
    return {(person_id, local_date): float(seconds)
            for person_id, local_date, seconds in rows}


def add_free_time_usage(person_id: str, local_date: str, seconds: float) -> None:
    if seconds <= 0:
        return
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS free_time_usage (
                person_id TEXT NOT NULL,
                local_date TEXT NOT NULL,
                used_seconds REAL NOT NULL DEFAULT 0,
                updated_at REAL NOT NULL,
                PRIMARY KEY (person_id, local_date)
            )
        """)
        conn.execute("""
            INSERT INTO free_time_usage (person_id, local_date, used_seconds, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(person_id, local_date) DO UPDATE SET
                used_seconds = free_time_usage.used_seconds + excluded.used_seconds,
                updated_at = excluded.updated_at
        """, (person_id, local_date, float(seconds), time.time()))
        conn.commit()

def create_enrollment(
    person_id: str,
    reference_count: int,
) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO enrollments (
                person_id,
                enrollment_version,
                reference_count,
                enrolled_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                person_id,
                1,
                reference_count,
                time.time(),
            ),
        )
        conn.commit()
        
def get_enrollments() -> List[Dict[str, Any]]:
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT
                person_id,
                enrollment_version,
                reference_count,
                enrolled_at,
                last_seen_at
            FROM enrollments
            ORDER BY id ASC
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
        for (
            person_id,
            version,
            reference_count,
            enrolled_at,
            last_seen_at,
        ) in rows
    ]

def create_employee(
    employee_id: str,
    name: str,
) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO employees (
                employee_id,
                name,
                created_at
            )
            VALUES (?, ?, ?)
            """,
            (
                employee_id,
                name,
                time.time(),
            ),
        )
        conn.commit()


def get_employees() -> List[Dict[str, Any]]:
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT employee_id, name, created_at
            FROM employees
            ORDER BY id ASC
            """
        ).fetchall()

    return [
        {
            "employee_id": employee_id,
            "name": name,
            "created_at": created_at,
        }
        for employee_id, name, created_at in rows
    ]

def save_event(
    timestamp: float,
    event_type: str,
    payload: Dict[str, Any],
) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO events (timestamp, type, payload)
            VALUES (?, ?, ?)
            """,
            (
                timestamp,
                event_type,
                json.dumps(payload),
            ),
        )
        conn.commit()


def get_events(limit: int = 50) -> List[Dict[str, Any]]:
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT timestamp, type, payload
            FROM events
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return [
        {
            "timestamp": timestamp,
            "type": event_type,
            "payload": json.loads(payload),
        }
        for timestamp, event_type, payload in reversed(rows)
    ]

def set_integration_state(
    key: str,
    value: str,
) -> None:
    DB_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS integration_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )

        conn.execute(
            """
            INSERT INTO integration_state (key, value)
            VALUES (?, ?)
            ON CONFLICT(key)
            DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )

        conn.commit()

def get_integration_state(
    key: str,
    default: str = "",
) -> str:
    DB_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS integration_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        row = conn.execute(
            """
            SELECT value
            FROM integration_state
            WHERE key = ?
            """,
            (key,),
        ).fetchone()

    if row is None:
        return default

    return str(row[0])

def save_protocol_event(
    timestamp: float,
    event_type: str,
    payload: Dict[str, Any],
    seq: int,
) -> bool:
    """
    Persist engine event dan checkpoint dalam satu transaksi.

    Returns:
        True  -> event baru disimpan
        False -> seq sudah pernah disimpan
    """
    DB_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS protocol_events (
                seq INTEGER PRIMARY KEY,
                timestamp REAL NOT NULL,
                type TEXT NOT NULL,
                payload TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS integration_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        existing = conn.execute(
            """
            SELECT 1
            FROM protocol_events
            WHERE seq = ?
            """,
            (seq,),
        ).fetchone()

        if existing is not None:
            return False

        conn.execute(
            """
            INSERT INTO protocol_events (
                seq,
                timestamp,
                type,
                payload
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                seq,
                timestamp,
                event_type,
                json.dumps(payload),
            ),
        )

        conn.execute(
            """
            INSERT INTO integration_state (key, value)
            VALUES ('engine_last_event_seq', ?)
            ON CONFLICT(key)
            DO UPDATE SET value = excluded.value
            """,
            (str(seq),),
        )

        conn.commit()

        return True


def get_protocol_events(event_type: str | None = None, limit: int = 1000) -> List[Dict[str, Any]]:
    init_database()
    query = "SELECT seq, timestamp, type, payload FROM protocol_events"
    params: list[Any] = []
    if event_type is not None:
        query += " WHERE type = ?"
        params.append(event_type)
    query += " ORDER BY seq ASC LIMIT ?"
    params.append(limit)
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(query, params).fetchall()
    return [{"seq": seq, "timestamp": timestamp, "type": stored_type,
             "payload": json.loads(payload)} for seq, timestamp, stored_type, payload in rows]


def save_detection_frame(message: Dict[str, Any], observed_at: float) -> bool:
    """Persist one enriched view.frame and its boxes atomically and idempotently."""
    camera_id = str(message.get("camera_id") or "")
    if not camera_id:
        raise ValueError("view.frame must contain camera_id")
    stream_epoch = int(message.get("stream_epoch") or 0)
    pts = float(message.get("pts") or 0.0)
    boxes = message.get("boxes") if isinstance(message.get("boxes"), list) else []

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("""
            INSERT OR IGNORE INTO detection_frames (
                camera_id, stream_epoch, pts, observed_at, width, height, fps, people_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            camera_id, stream_epoch, pts, float(observed_at),
            int(message.get("width") or 0), int(message.get("height") or 0),
            float(message.get("fps") or 0.0), len(boxes),
        ))
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
            conn.execute("""
                INSERT INTO track_observations (
                    frame_id, camera_id, stream_epoch, pts, track_uuid, person_id,
                    confidence, x1, y1, x2, y2, session_elapsed, presence_status,
                    daily_used_seconds, remaining_seconds
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                frame_id, camera_id, stream_epoch, pts, track_uuid, person_text,
                float(raw_box.get("confidence") or raw_box.get("similarity") or 0.0),
                *(float(value) for value in bbox), elapsed, status,
                float(raw_box.get("daily_used_seconds") or 0.0),
                float(raw_box["remaining_seconds"])
                if raw_box.get("remaining_seconds") is not None else None,
            ))
            conn.execute("""
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
            """, (
                camera_id, stream_epoch, track_uuid, person_text,
                max(0.0, pts - elapsed), pts, observed_at, observed_at,
                elapsed, status,
            ))
            if person_text:
                conn.execute(
                    "UPDATE enrollments SET last_seen_at = ? WHERE person_id = ?",
                    (observed_at, person_text),
                )

        if live_tracks:
            placeholders = ",".join("?" for _ in live_tracks)
            conn.execute(f"""
                UPDATE track_sessions
                SET ended_pts = ?, last_observed_at = ?, is_active = 0
                WHERE camera_id = ? AND stream_epoch = ? AND is_active = 1
                  AND track_uuid NOT IN ({placeholders})
            """, (pts, observed_at, camera_id, stream_epoch, *sorted(live_tracks)))
        else:
            conn.execute("""
                UPDATE track_sessions
                SET ended_pts = ?, last_observed_at = ?, is_active = 0
                WHERE camera_id = ? AND stream_epoch = ? AND is_active = 1
            """, (pts, observed_at, camera_id, stream_epoch))
        conn.commit()
    return True


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
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(query, params).fetchall()
    keys = ("camera_id", "stream_epoch", "pts", "track_uuid", "person_id",
            "confidence", "x1", "y1", "x2", "y2", "session_elapsed",
            "presence_status", "daily_used_seconds", "remaining_seconds")
    return [dict(zip(keys, row)) for row in reversed(rows)]
