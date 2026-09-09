import csv
import json
from collections import defaultdict
from pathlib import Path

from app.config import LESSONS_CSV, TUTORS_CSV
from app.db import connect, init_db


def _empty(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def assign_exam_pairs(rows: list[dict]) -> None:
    """L009/L010 share a note 'exam pair'. Group by slot + tutor + room."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        note = (row.get("note") or "").lower()
        if "exam pair" not in note:
            continue
        key = (row["date"], row["start_time"], row["tutor_id"], row["room"])
        groups[key].append(row)

    for index, group in enumerate(groups.values(), start=1):
        pair_id = f"PAIR{index:03d}"
        for row in group:
            row["pair_group_id"] = pair_id


def snapshot(row: dict) -> str:
    return json.dumps(
        {
            "tutor_id": row["tutor_id"],
            "room": row["room"],
            "date": row["date"],
            "start_time": row["start_time"],
            "duration_min": int(row["duration_min"]),
            "student": row["student"],
            "status": row["status"],
        },
        sort_keys=True,
    )


def load_seed(tutors_csv: Path | None = None, lessons_csv: Path | None = None) -> None:
    conn = connect()
    init_db(conn)
    conn.execute("DELETE FROM lessons")
    conn.execute("DELETE FROM tutors")

    with (tutors_csv or TUTORS_CSV).open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            conn.execute(
                """
                INSERT INTO tutors (tutor_id, tutor_name, subject, phone)
                VALUES (:tutor_id, :tutor_name, :subject, :phone)
                """,
                row,
            )

    with (lessons_csv or LESSONS_CSV).open(newline="", encoding="utf-8") as handle:
        lessons = list(csv.DictReader(handle))

    for row in lessons:
        row["cancelled_at"] = _empty(row.get("cancelled_at"))
        row["note"] = _empty(row.get("note"))
        row["pair_group_id"] = None
        row["duration_min"] = int(row["duration_min"])

    assign_exam_pairs(lessons)

    for row in lessons:
        row["notified_as_json"] = snapshot(row)
        conn.execute(
            """
            INSERT INTO lessons (
                lesson_id, date, start_time, duration_min, student, tutor_id,
                room, status, cancelled_at, note, pair_group_id, notified_as_json
            ) VALUES (
                :lesson_id, :date, :start_time, :duration_min, :student, :tutor_id,
                :room, :status, :cancelled_at, :note, :pair_group_id, :notified_as_json
            )
            """,
            row,
        )

    conn.commit()
    conn.close()


if __name__ == "__main__":
    load_seed()
    print("Seed loaded.")
