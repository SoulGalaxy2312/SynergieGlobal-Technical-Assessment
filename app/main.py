import json
from datetime import date, datetime, time

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from app.config import LATE_CANCEL_HOURS, TODAY, TIMEZONE
from app.conflicts import blocking_conflicts_for_new, find_conflicts
from app.db import connect
from app.schemas import CancelRequest, ConflictReport, LessonCreate, LessonOut
from app.seed import load_seed, snapshot
from app.timeutil import combine_local, parse_hhmm

app = FastAPI(
    title="Bright Path scheduling",
    description="Conflict-aware booking for one week of seed data. Clock is pinned to 2026-03-10.",
    version="0.1.0",
)


def _row_to_lesson(row) -> dict:
    payload = dict(row)
    notified = payload.get("notified_as_json")
    payload["notified_as"] = json.loads(notified) if notified else None
    payload.pop("notified_as_json", None)
    return payload


def _fetch_lessons(from_date: date | None = None, to_date: date | None = None) -> list[dict]:
    conn = connect()
    sql = "SELECT * FROM lessons"
    params: list = []
    clauses = []
    if from_date:
        clauses.append("date >= ?")
        params.append(from_date.isoformat())
    if to_date:
        clauses.append("date <= ?")
        params.append(to_date.isoformat())
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY date, start_time, lesson_id"
    rows = [_row_to_lesson(row) for row in conn.execute(sql, params)]
    conn.close()
    return rows


def _next_lesson_id() -> str:
    conn = connect()
    row = conn.execute(
        "SELECT lesson_id FROM lessons ORDER BY CAST(substr(lesson_id, 2) AS INTEGER) DESC LIMIT 1"
    ).fetchone()
    conn.close()
    if row is None:
        return "L001"
    number = int(row["lesson_id"][1:]) + 1
    return f"L{number:03d}"


@app.on_event("startup")
def startup() -> None:
    load_seed()


@app.get("/health")
def health() -> dict:
    return {"ok": True, "today": TODAY.isoformat(), "timezone": str(TIMEZONE)}


@app.get("/lessons", response_model=list[LessonOut])
def list_lessons(day: date | None = Query(default=None, alias="date")) -> list[dict]:
    if day:
        return _fetch_lessons(from_date=day, to_date=day)
    return _fetch_lessons()


@app.get("/conflicts", response_model=ConflictReport)
def conflicts(
    from_date: date = Query(default=date(2026, 3, 3), alias="from"),
    to_date: date = Query(default=date(2026, 3, 10), alias="to"),
) -> dict:
    lessons = _fetch_lessons(from_date=from_date, to_date=to_date)
    found = find_conflicts(lessons)
    return {
        "today": TODAY.isoformat(),
        "from_date": from_date.isoformat(),
        "to_date": to_date.isoformat(),
        "count": len(found),
        "conflicts": found,
    }


@app.post("/lessons", response_model=LessonOut, status_code=201)
def create_lesson(body: LessonCreate) -> dict | JSONResponse:
    try:
        body.validate_duration()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    conn = connect()
    tutor = conn.execute(
        "SELECT tutor_id FROM tutors WHERE tutor_id = ?", (body.tutor_id,)
    ).fetchone()
    conn.close()
    if tutor is None:
        raise HTTPException(status_code=404, detail=f"Unknown tutor_id {body.tutor_id}")

    lesson_id = _next_lesson_id()
    candidate = {
        "lesson_id": lesson_id,
        "date": body.date.isoformat(),
        "start_time": body.start_time.strftime("%H:%M"),
        "duration_min": body.duration_min,
        "student": body.student,
        "tutor_id": body.tutor_id,
        "room": body.room,
        "status": "booked",
        "cancelled_at": None,
        "note": body.note,
        "pair_group_id": body.pair_group_id,
    }

    blockers = blocking_conflicts_for_new(_fetch_lessons(), candidate)
    if blockers:
        return JSONResponse(
            status_code=409,
            content={
                "detail": "Booking conflicts with existing lessons.",
                "conflicts": blockers,
            },
        )

    candidate["notified_as_json"] = snapshot(candidate)
    conn = connect()
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
        candidate,
    )
    conn.commit()
    row = conn.execute("SELECT * FROM lessons WHERE lesson_id = ?", (lesson_id,)).fetchone()
    conn.close()
    return _row_to_lesson(row)


@app.post("/lessons/{lesson_id}/cancel", response_model=LessonOut)
def cancel_lesson(lesson_id: str, body: CancelRequest | None = None) -> dict:
    body = body or CancelRequest()
    conn = connect()
    row = conn.execute("SELECT * FROM lessons WHERE lesson_id = ?", (lesson_id,)).fetchone()
    if row is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Lesson not found")
    if row["status"] == "cancelled":
        conn.close()
        raise HTTPException(status_code=409, detail="Lesson is already cancelled")

    now = datetime.combine(TODAY, time(12, 0), tzinfo=TIMEZONE)
    start = combine_local(date.fromisoformat(row["date"]), parse_hhmm(row["start_time"]))
    hours_before = (start - now).total_seconds() / 3600
    late = body.reason == "family" and 0 <= hours_before < LATE_CANCEL_HOURS

    cancelled_at = now.isoformat()
    note = row["note"] or ""
    extra = f"cancelled:{body.reason}" + (";late" if late else ";free")
    new_note = f"{note}; {extra}".strip("; ")

    # Keep notified_as_json: the tutor was already told about this slot.
    conn.execute(
        """
        UPDATE lessons
        SET status = 'cancelled', cancelled_at = ?, note = ?
        WHERE lesson_id = ?
        """,
        (cancelled_at, new_note, lesson_id),
    )
    conn.commit()
    updated = conn.execute("SELECT * FROM lessons WHERE lesson_id = ?", (lesson_id,)).fetchone()
    conn.close()
    return _row_to_lesson(updated)

