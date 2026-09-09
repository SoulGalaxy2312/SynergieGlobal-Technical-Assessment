# Bright Path scheduling (take-home)

FastAPI + SQLite service for one week of Bright Path centre bookings.

Pinned clock: **2026-03-10**, timezone **Asia/Ho_Chi_Minh**. All “today” / late-cancel maths use this date, never the machine clock.

## Setup

```bash
cd /Users/P035243/Desktop/SynergieGlobal-Technical-Assessment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Startup reloads seed from `data/*.csv` into `app.db` (destructive). You can also seed without the server:

```bash
python -m app.seed
```

## Health and conflicts

```bash
curl -s http://127.0.0.1:8000/health
curl -s "http://127.0.0.1:8000/conflicts?from=2026-03-03&to=2026-03-10"
```

### Expected seed conflicts

| Kind | Lessons | Notes |
| --- | --- | --- |
| `student_overlap` | L007 / L008 | Lê Minh Châu in R3 and R2 at 09:00 on 2026-03-04 |
| `tutor_two_rooms` | L033 / L034 | T1 in R1 and R2 at 09:00 on 2026-03-10 |
| `over_daily_cap` | T1 on 2026-03-06 | Seven occupying lessons; cap is 6 |
| `open_on_closed_day` | L032 | Monday 2026-03-09, rooms should be closed for cleaning |

**Not a clash:** L009 / L010 (exam pair, same tutor, same room, tagged `pair_group_id`).

## Booking checks after seed

POST T1 at 2026-03-10 09:00 must **409** (tutor already in two rooms that hour).

```bash
curl -s -o /dev/stderr -w "%{http_code}\n" -X POST http://127.0.0.1:8000/lessons \
  -H 'Content-Type: application/json' \
  -d '{"date":"2026-03-10","start_time":"09:00","duration_min":60,"student":"New Student","tutor_id":"T1","room":"R3"}'
```

POST T2 into R3 at 09:00 must **201**.

```bash
curl -s -o /dev/stderr -w "%{http_code}\n" -X POST http://127.0.0.1:8000/lessons \
  -H 'Content-Type: application/json' \
  -d '{"date":"2026-03-10","start_time":"09:00","duration_min":60,"student":"New Student","tutor_id":"T2","room":"R3"}'
```

Cancelled rows do not occupy a slot. `no_show` still occupies (the room and tutor were used).