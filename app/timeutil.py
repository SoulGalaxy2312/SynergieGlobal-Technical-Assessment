from datetime import date, datetime, time, timedelta

from app.config import TIMEZONE


def parse_hhmm(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def combine_local(day: date, start: time) -> datetime:
    return datetime.combine(day, start, tzinfo=TIMEZONE)


def interval_end(day: date, start: time, duration_min: int) -> datetime:
    return combine_local(day, start) + timedelta(minutes=duration_min)


def intervals_overlap(
    day_a: date,
    start_a: time,
    duration_a: int,
    day_b: date,
    start_b: time,
    duration_b: int,
) -> bool:
    if day_a != day_b:
        return False
    begin_a = combine_local(day_a, start_a)
    end_a = interval_end(day_a, start_a, duration_a)
    begin_b = combine_local(day_b, start_b)
    end_b = interval_end(day_b, start_b, duration_b)
    return begin_a < end_b and begin_b < end_a

