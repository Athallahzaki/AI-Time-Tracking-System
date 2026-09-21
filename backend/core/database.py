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
