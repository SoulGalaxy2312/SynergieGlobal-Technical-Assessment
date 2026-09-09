from datetime import date, time
from typing import Optional

from pydantic import BaseModel, Field

from app.config import ALLOWED_DURATIONS


class LessonOut(BaseModel):
    lesson_id: str
    date: str
    start_time: str
    duration_min: int
    student: str
    tutor_id: str
    room: str
    status: str
    cancelled_at: Optional[str] = None
    note: Optional[str] = None
    pair_group_id: Optional[str] = None
    notified_as: Optional[dict] = None


class ConflictOut(BaseModel):
    kind: str
    lesson_ids: list[str]
    detail: str


class ConflictReport(BaseModel):
    today: str
    from_date: str
    to_date: str
    count: int
    conflicts: list[ConflictOut]


class LessonCreate(BaseModel):
    date: date
    start_time: time
    duration_min: int = Field(..., description="60 or 90")
    student: str
    tutor_id: str
    room: str
    pair_group_id: Optional[str] = None
    note: Optional[str] = None

    def validate_duration(self) -> None:
        if self.duration_min not in ALLOWED_DURATIONS:
            raise ValueError("duration_min must be 60 or 90")


class CancelRequest(BaseModel):
    reason: str = "family"
