"""Scheduling rules that the spreadsheet already breaks

Two different callers use this module:
- GET /conflicts - find_conflicts(all rows) - report EVERY clash in the week
- POST /lessons - blocking_conflicts_for_new(...) - 409 only for "hard" clashes

Seed is allowed to contain clashes. We need delete or "fix" those rows here.
We only describe them.

Kinds you will see:

    student_overlap     same student, overlapping clock time            e.g. L007 + L008
    tutor_two_rooms     same tutor, two different rooms                 e.g. L033 + L034
    room_overlap        same room, not an exam pair                     (none in seed)
    pair_too_large      exam pair with more than 2 students             (none in seed)
    over_daily_cap      tutor has more than 6 occupying lessons         e.g. T1 on 6 Mar
    open_on_closed_day  occupying lesson on Monday                      e.g. L032


A pair of lessons can emit more than one kind. That is intentional
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, time

from app.config import (
    CENTRE_CLOSED_WEEKDAY,
    MAX_PAIR_SIZE,
    MAX_TUTOR_LESSONS_PER_DAY,
    OCCUPYING_STATUSES,
)
from app.timeutil import intervals_overlap, parse_hhmm


def occupying(lessons: list[dict]) -> list[dict]:
    """Rows that still hold a tutor + room on the clock

    booked  - family is expected, slot is taken
    no_show     - student did not arrive, but the slot was still used (L015) 
    cancelled   - slot is free again (L005 family cancel, L017 tutor sick)

    Only occupying rows can clash. A cancelled 14:00 must not block a replacement
    """
    return [row for row in lessons if row["status"] in OCCUPYING_STATUSES]


def parse_lesson_day(row: dict) -> date:
    return date.fromisoformat(row["date"])


def parse_lesson_start(row: dict) -> time:
    return parse_hhmm(row["start_time"])


def find_conflicts(lessons: list[dict]) -> list[dict]:
    """Scan the week and return every clash.

    Three passes:
        1. Pairwise time overlap            - student / tutor / room
        2. Count exam-pair size             - pair_too_large
        3. Count per tutor-day and weekday  - cap + Monday
    
    Pass 1 needs two rows on the clock at once
    Pass 2-3 are counts, so they do not need an overlap check.
    """
    found: list[dict] = []
    active = occupying(lessons)


    # --- Pass 1: every pair of occupying lessons that overlap in time -------
    # i / i + 1: each pair once (L007 vs L008, never also L008 vs L007)
    for i, left in enumerate(active):
        for right in active[i + 1 :]:
            # Same calendar day AND [start, start + duration) intervals overlap.
            # Touching ends do not clash: 11:30+60min ends 12:30, next at 12:30 is OK.
            # L021 (11:30) and L022 (13:00) have a gap - they never enter this block
            if not intervals_overlap(
                parse_lesson_day(left),
                parse_lesson_start(left),
                left["duration_min"],
                parse_lesson_day(right),
                parse_lesson_start(right),
                right["duration_min"],
            ):
                continue

            ids = sorted([left["lesson_id"], right["lesson_id"]])

            # Owner story: student booked into two places at once.
            # Seed: L007 T3/R3 and L008 T2/R2, both 4 Mar 09:00, Le Minh Chau
            if left["student"] == right["student"]:
                found.append(
                    {
                        "kind": "student_overlap",
                        "lesson_ids": ids,
                        "detail": (
                            f"{left['student']} is booked in {left['room']} and "
                            f"{right['room']} at the same time."
                        ),
                    }
                )
            # Hard rule: a tutor can only be in one room at a time.
            # Different rooms is required - an exam pair is SAME room, so it
            # must not fire here. Seed: L033 R1 and L034 R2, T1, 10 Mar 09:00.
            if left["tutor_id"] == right["tutor_id"] and left["room"] != right["room"]:
                found.append(
                    {
                        "kind": "tutor_two_rooms",
                        "lesson_ids": ids,
                        "detail": (
                            f"{left['tutor_id']} is in {left['room']} and "
                            f"{right['room']} at the same time."
                        ),
                    }
                )

            # Hard rule: a room holds one lesson, unless Mai's exam pair.
            # L009 + L010 share pair_group_id PAIR001 - _same_pair is True - skip
            # Two unpaired lessons in R1 at the same time would be room_overlap
            if left["room"] == right["room"] and not _same_pair(left, right):
                found.append(
                    {
                        "kind": "room_overlap",
                        "lesson_ids": ids,
                        "detail": (
                            f"{left['room']} holds two lessons that are not an exam pair."
                        ),
                    }
                )

    # --- Pass 2: exam pair may be two students, not three ----
    # pair_group_id is set at seed from notes containing "exam pair".
    # POST /lessons can send the same id to join a pair; a third student 409s
    pair_sizes: dict[str, list[str]] = defaultdict(list)
    for row in active:
        pair_id = row.get("pair_group_id")
        if pair_id:
            pair_sizes[pair_id].append(row["lesson_id"])
    for pair_id, ids in pair_sizes.items():
        unique = sorted(set(ids))
        if len(unique) > MAX_PAIR_SIZE:
            found.append(
                {
                    "kind": "pair_too_large",
                    "lesson_ids": unique,
                    "detail": f"Exam pair {pair_id} has {len(unique)} students; max is {MAX_PAIR_SIZE}.",
                }
            )

    # --- Pass 3a: tutor load (reported, not a POST blocker) ------
    # Owner wants max 6. Mai already put T1 on 7 occupying lessons on 6 Mar:
    # L018, L021, L022, L024, L025, L026, L027.
    # We still load the seed; GET /conflicts shows the over-cap
    by_tutor_day: dict[tuple[str, str], list[str]] = defaultdict(list)
    for row in occupying(lessons):
        by_tutor_day[(row["tutor_id"], row["date"])].append(row["lesson_id"])
    for (tutor_id, day), ids in sorted(by_tutor_day.items()):
        if len(ids) > MAX_TUTOR_LESSONS_PER_DAY:
            found.append(
                {
                    "kind": "over_daily_cap",
                    "lesson_ids": sorted(ids),
                    "detail": (
                        f"{tutor_id} has {len(ids)} occupying lessons on {day}; "
                        f"cap is {MAX_TUTOR_LESSONS_PER_DAY}."
                    ),
                }
            )

    # --- Pass 3b: Monday is closed (reported, not a POST blocker) -----
    # weekday() 0 = Monday. Seed L032 is 9 Mar, family asked to move off Sunday.
    # We flag it; we do not delete it; we do not 409 new Monday bookings
    for row in occupying(lessons):
        day = parse_lesson_day(row)
        if day.weekday() == CENTRE_CLOSED_WEEKDAY:
            found.append(
                {
                    "kind": "open_on_closed_day",
                    "lesson_ids": [row["lesson_id"]],
                    "detail": f"{row['lesson_id']} is on Monday, when rooms are cleaned.",
                }
            )

    return found


def _same_pair(left: dict, right: dict) -> bool:
    """
        True only if both rows share a non-empty pair_group_id

        Empty/None is not a pair: two lessons with no id are a room clash, not a pair.
        Both must match - one paired + one stranger in the same room is still illegal.
    """
    left_pair = left.get("pair_group_id")
    right_pair = right.get("pair_group_id")
    return bool(left_pair) and left_pair == right_pair


def blocking_conflicts_for_new(existing: list[dict], candidate: dict) -> list[dict]:
    """
        Conflicts that should reject POST /lessons with HTTP 409

        Hard (block): student_overlap, tutor_two_rooms, room_overlap, pair_too_large
        Soft(report only): over_daily_cap, open_on_closed_day

        Why the split: the seed already violates cap (T1 Friday) and Monday (L032)
        Blocking those on create while leaving history in place would be inconsistent

        We re-run find_conflicts on existing + candidate, then keep only rows that
        (1) are a hard kind and (2) actually mention the new lesson_id.
        Filter(2) drops leftover seed clashes (L007/L008) so they do not 409 an
        unrelated Tuesday booking.
    """
    kinds = {"student_overlap", "tutor_two_rooms", "room_overlap", "pair_too_large"}
    return [
        item
        for item in find_conflicts(existing + [candidate])
        if item["kind"] in kinds and candidate["lesson_id"] in item["lesson_ids"]
    ]
