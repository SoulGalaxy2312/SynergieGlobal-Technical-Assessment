import sqlite3
from pathlib import Path

from app.config import DB_PATH

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS tutors (
    tutor_id TEXT PRIMARY KEY,
    tutor_name TEXT NOT NULL,
    subject TEXT NOT NULL,
    phone TEXT
);

CREATE TABLE IF NOT EXISTS lessons (
    lesson_id TEXT PRIMARY KEY,
    date TEXT NOT NULL,
    start_time TEXT NOT NULL,
    duration_min INTEGER NOT NULL CHECK (duration_min IN (60, 90)),
    student TEXT NOT NULL,
    tutor_id TEXT NOT NULL REFERENCES tutors(tutor_id),
    room TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('booked', 'cancelled', 'no_show')),
    cancelled_at TEXT,
    note TEXT,
    pair_group_id TEXT,
    notified_as_json TEXT,
    CHECK (
        (status = 'cancelled' AND cancelled_at IS NOT NULL)
        OR (status != 'cancelled' AND cancelled_at IS NULL)
    )
);
"""


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()