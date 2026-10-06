import os
import sqlite3
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Any

import config
from temporal_engine import ViolationEvent

logger = logging.getLogger(__name__)

def _get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Returns a connection to the SQLite database, ensuring directory exists."""
    path = db_path or config.DATABASE_PATH
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn

def init_db(db_path: Optional[str] = None):
    """
    Initializes the SQLite database schema if it does not already exist.
    Creates table `ppe_violations` with all required and metadata columns.
    """
    try:
        with _get_connection(db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ppe_violations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT UNIQUE NOT NULL,
                    track_id INTEGER NOT NULL,
                    violation_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    decision_score REAL NOT NULL,
                    evidence_path TEXT,
                    timestamp TEXT NOT NULL,
                    status TEXT NOT NULL,
                    frame_index INTEGER,
                    missing_ratio REAL,
                    observable_frames INTEGER,
                    is_zone_violation INTEGER,
                    message TEXT
                )
            """)
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to initialize database at {db_path or config.DATABASE_PATH}: {e}")

def save_violation(event: ViolationEvent, evidence_path: Optional[str] = None, db_path: Optional[str] = None) -> bool:
    """
    Inserts a confirmed violation event into the `ppe_violations` table.
    Idempotent: Uses `INSERT OR IGNORE` on event_id to prevent duplicates.

    Returns:
        bool: True if inserted (or already existing), False on unexpected database error.
    """
    init_db(db_path)
    try:
        ts_str = datetime.fromtimestamp(event.timestamp).strftime("%Y-%m-%d %H:%M:%S") if isinstance(event.timestamp, (int, float)) else str(event.timestamp)
        with _get_connection(db_path) as conn:
            conn.execute("""
                INSERT OR IGNORE INTO ppe_violations (
                    event_id,
                    track_id,
                    violation_type,
                    severity,
                    decision_score,
                    evidence_path,
                    timestamp,
                    status,
                    frame_index,
                    missing_ratio,
                    observable_frames,
                    is_zone_violation,
                    message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                event.event_id,
                event.track_id,
                event.violation_type.value,
                event.severity.value,
                float(event.decision_score),
                evidence_path or "",
                ts_str,
                event.status.value,
                event.frame_index,
                float(event.missing_ratio),
                event.observable_frames,
                1 if event.is_zone_violation else 0,
                event.message
            ))
            conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error saving violation event {event.event_id} to database: {e}")
        return False

def get_recent_violations(limit: int = 100, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieves the most recent PPE violations ordered by id descending."""
    init_db(db_path)
    try:
        with _get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM ppe_violations ORDER BY id DESC LIMIT ?", (limit,))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"Error querying recent violations: {e}")
        return []

def get_violation_count(db_path: Optional[str] = None) -> int:
    """Returns the total number of recorded PPE violations."""
    init_db(db_path)
    try:
        with _get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM ppe_violations")
            return cursor.fetchone()[0]
    except Exception as e:
        logger.error(f"Error querying violation count: {e}")
        return 0

def get_violation_by_id(event_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retrieves a single violation record by its unique event_id."""
    init_db(db_path)
    try:
        with _get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM ppe_violations WHERE event_id = ?", (event_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"Error querying violation by event_id {event_id}: {e}")
        return None
