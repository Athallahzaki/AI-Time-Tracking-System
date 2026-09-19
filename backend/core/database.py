from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List


DB_PATH = Path(__file__).resolve().parents[1] / "data" / "backend.db"


def init_database() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

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
        conn.commit()


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