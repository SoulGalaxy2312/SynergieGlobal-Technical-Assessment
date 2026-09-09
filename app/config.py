from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = ROOT / "app.db"
TUTORS_CSV = DATA_DIR / "tutors.csv"
LESSONS_CSV = DATA_DIR / "lessons_export.csv"

# Seed week is 3–10 Mar 2026. The export was taken on this date.
# All "today" / cut-off logic uses this, never the machine clock.
TODAY = date(2026, 3, 10)
TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")

CENTRE_CLOSED_WEEKDAY = 0  # Monday
MAX_TUTOR_LESSONS_PER_DAY = 6
LATE_CANCEL_HOURS = 4
CUTOFF_HOUR = 16
MAX_PAIR_SIZE = 2
OCCUPYING_STATUSES = frozenset({"booked", "no_show"})
ALLOWED_DURATIONS = frozenset({60, 90})