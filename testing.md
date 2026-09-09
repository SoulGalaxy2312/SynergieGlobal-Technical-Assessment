# Manual test scenarios

Pinned clock: **2026-03-10**, `Asia/Ho_Chi_Minh`.  
Base URL: `http://127.0.0.1:8000`

Startup **wipes** `app.db` and reloads `data/*.csv`. After POSTs that change state, restart uvicorn (or `python -m app.seed`) before the next “clean seed” scenario.

```bash
cd /Users/P035243/Desktop/SynergieGlobal-Technical-Assessment
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

Interactive API: http://127.0.0.1:8000/docs

---

## 1. Clock is pinned (not the laptop date)

```bash
curl -s http://127.0.0.1:8000/health
```

**Expect:** `"today": "2026-03-10"` and timezone `Asia/Ho_Chi_Minh`.  
If this shows 2026-09-09, the interview story is already wrong.

---

## 2. Seed audit — dirty week is visible, not cleaned

```bash
curl -s "http://127.0.0.1:8000/conflicts?from=2026-03-03&to=2026-03-10"
```

**Expect all of these kinds present:**

| Kind | Lesson ids | Why |
|---|---|---|
| `student_overlap` | L007, L008 | Le Minh Chau in R3 and R2, 4 Mar 09:00 |
| `tutor_two_rooms` | L033, L034 | T1 in R1 and R2, 10 Mar 09:00 |
| `over_daily_cap` | L018, L021, L022, L024, L025, L026, L027 | T1 has 7 occupying lessons on 6 Mar |
| `open_on_closed_day` | L032 | Monday 9 Mar |

**Expect these not to be clashes:**

| Rows | Why not a clash |
|---|---|
| L009, L010 | Exam pair (`pair_group_id`), same tutor, same room |
| L021, L022 | 11:30+60 ends 12:30; next starts 13:00 — gap, not overlap |
| L005 | `cancelled` — does not occupy |
| L017 | `cancelled` (tutor sick) — does not occupy |

**Expect no** `room_overlap` and **no** `pair_too_large` on unmodified seed.

---

## 3. Filter the audit by date

```bash
curl -s "http://127.0.0.1:8000/conflicts?from=2026-03-10&to=2026-03-10"
```

**Expect:** `tutor_two_rooms` for L033/L034.  
**Do not expect:** L007/L008 or Friday cap (those dates are outside the window).

```bash
curl -s "http://127.0.0.1:8000/lessons?date=2026-03-10"
```

**Expect:** L033 and L034 only (two booked rows, T1, 09:00, R1 and R2).

```bash
curl -s "http://127.0.0.1:8000/lessons?date=2026-03-04"
```

**Expect:** L007–L012, including the exam pair and Chau’s double-book.

---

## 4. Occupying vs cancelled vs no-show

### 4a. Cancelled slot is free (L005)

L005 is T2 / R2 / 3 Mar 14:00, status `cancelled`.

```bash
curl -s -w "\nHTTP %{http_code}\n" -X POST http://127.0.0.1:8000/lessons \
  -H 'Content-Type: application/json' \
  -d '{"date":"2026-03-03","start_time":"14:00","duration_min":60,"student":"Replacement","tutor_id":"T2","room":"R2"}'
```

**Expect:** `201`. The cancelled row must not block the room or tutor.

Restart the server before 4b (this POST is now in the DB).

### 4b. No-show still occupies (L015)

L015 is T2 / R2 / 5 Mar 13:00, `no_show`.

```bash
curl -s -w "\nHTTP %{http_code}\n" -X POST http://127.0.0.1:8000/lessons \
  -H 'Content-Type: application/json' \
  -d '{"date":"2026-03-05","start_time":"13:00","duration_min":60,"student":"Someone Else","tutor_id":"T3","room":"R2"}'
```

**Expect:** `409` with `room_overlap` (R2 still held).  
A no-show used the slot; it is not a hole in the diary.

---

## 5. Hard rejects on create (409)

Use a **fresh seed** (restart) before this section.

### 5a. Tutor already in two rooms — owner’s failure mode

```bash
curl -s -w "\nHTTP %{http_code}\n" -X POST http://127.0.0.1:8000/lessons \
  -H 'Content-Type: application/json' \
  -d '{"date":"2026-03-10","start_time":"09:00","duration_min":60,"student":"New Student","tutor_id":"T1","room":"R3"}'
```

**Expect:** `409`, kind `tutor_two_rooms` (T1 is already in R1 and R2).

### 5b. Same student, two places

```bash
curl -s -w "\nHTTP %{http_code}\n" -X POST http://127.0.0.1:8000/lessons \
  -H 'Content-Type: application/json' \
  -d '{"date":"2026-03-04","start_time":"09:00","duration_min":60,"student":"Le Minh Chau","tutor_id":"T1","room":"R1"}'
```

**Expect:** `409`, kind `student_overlap` (Chau already has L007 and L008 at 09:00).  
T1/R1 is free at that hour on 4 Mar, so this is the **student** rule, not the room rule.

### 5c. Room taken, not an exam pair

L001 holds R1 at 3 Mar 09:00 (T1). T3 is free then.

```bash
curl -s -w "\nHTTP %{http_code}\n" -X POST http://127.0.0.1:8000/lessons \
  -H 'Content-Type: application/json' \
  -d '{"date":"2026-03-03","start_time":"09:00","duration_min":60,"student":"Walk In","tutor_id":"T3","room":"R1"}'
```

**Expect:** `409`, kind `room_overlap`.

### 5d. Partial time overlap (not the same start)

L003 is T1 / R1 / 3 Mar 10:30 for **90** minutes (until 12:00). A 10:00 start overlaps that.

```bash
curl -s -w "\nHTTP %{http_code}\n" -X POST http://127.0.0.1:8000/lessons \
  -H 'Content-Type: application/json' \
  -d '{"date":"2026-03-03","start_time":"10:00","duration_min":60,"student":"Overlap Kid","tutor_id":"T1","room":"R1"}'
```

**Expect:** `409` (`tutor_two_rooms` and/or `room_overlap`).  
This is why UNIQUE(tutor, start_time) would be the wrong constraint: start times differ, intervals still collide.

### 5e. Third student on an exam pair

L009/L010 are `PAIR001` at 4 Mar 11:00, T1, R1.

```bash
curl -s -w "\nHTTP %{http_code}\n" -X POST http://127.0.0.1:8000/lessons \
  -H 'Content-Type: application/json' \
  -d '{"date":"2026-03-04","start_time":"11:00","duration_min":90,"student":"Third","tutor_id":"T1","room":"R1","pair_group_id":"PAIR001"}'
```

**Expect:** `409`, kind `pair_too_large` (and possibly room/tutor noise). Max pair size is 2.

---

## 6. Creates that must succeed (201)

Fresh seed.

### 6a. Free tutor, free room, new student — export morning

T2 and R3 are idle at 10 Mar 09:00 (T1 is the one double-booked).

```bash
curl -s -w "\nHTTP %{http_code}\n" -X POST http://127.0.0.1:8000/lessons \
  -H 'Content-Type: application/json' \
  -d '{"date":"2026-03-10","start_time":"09:00","duration_min":60,"student":"New Student","tutor_id":"T2","room":"R3"}'
```

**Expect:** `201`, new id `L035`, `status: booked`, `notified_as` filled.

### 6b. Intervals that only touch (exclusive end)

L004 is T3 / R3 / 3 Mar 10:30. A 09:00 / 90-minute lesson ends at **10:30** and must **not** overlap L004.

```bash
curl -s -w "\nHTTP %{http_code}\n" -X POST http://127.0.0.1:8000/lessons \
  -H 'Content-Type: application/json' \
  -d '{"date":"2026-03-03","start_time":"09:00","duration_min":90,"student":"Touching","tutor_id":"T3","room":"R3"}'
```

**Expect:** `201`. If this 409s, the overlap helper is using a closed-closed interval.

---

## 7. Soft rules — report, do not 409

Fresh seed.

### 7a. Eighth lesson for T1 on Friday (cap is 6)

T1 already has 7 occupying rows on 6 Mar. 14:00–15:00 is a gap (after L022, before L024). R1 is free.

```bash
curl -s -w "\nHTTP %{http_code}\n" -X POST http://127.0.0.1:8000/lessons \
  -H 'Content-Type: application/json' \
  -d '{"date":"2026-03-06","start_time":"14:00","duration_min":60,"student":"Eighth","tutor_id":"T1","room":"R1"}'
```

**Expect:** `201` (cap is not a create blocker).  
Then `GET /conflicts` — `over_daily_cap` for T1 on 2026-03-06 should list **8** ids.

### 7b. New booking on Monday

```bash
curl -s -w "\nHTTP %{http_code}\n" -X POST http://127.0.0.1:8000/lessons \
  -H 'Content-Type: application/json' \
  -d '{"date":"2026-03-09","start_time":"14:00","duration_min":60,"student":"Monday Kid","tutor_id":"T2","room":"R1"}'
```

**Expect:** `201`. Then `GET /conflicts` includes `open_on_closed_day` for the new id **and** L032.

Interview line: “If the owner says Monday is inviolable, add `open_on_closed_day` to `blocking_conflicts_for_new`.”

---

## 8. Validation and missing masters

```bash
# Unknown tutor
curl -s -w "\nHTTP %{http_code}\n" -X POST http://127.0.0.1:8000/lessons \
  -H 'Content-Type: application/json' \
  -d '{"date":"2026-03-10","start_time":"15:00","duration_min":60,"student":"X","tutor_id":"T99","room":"R1"}'
```

**Expect:** `404`.

```bash
# Duration not 60 or 90
curl -s -w "\nHTTP %{http_code}\n" -X POST http://127.0.0.1:8000/lessons \
  -H 'Content-Type: application/json' \
  -d '{"date":"2026-03-10","start_time":"15:00","duration_min":45,"student":"X","tutor_id":"T2","room":"R1"}'
```

**Expect:** `422`.

---

## 9. Cancel — frees the slot, keeps what the tutor was told

Fresh seed.

```bash
curl -s http://127.0.0.1:8000/lessons?date=2026-03-07
# L030 = T1 / R1 / 15:00 Bui An Nhien
```

```bash
curl -s -w "\nHTTP %{http_code}\n" -X POST http://127.0.0.1:8000/lessons/L030/cancel \
  -H 'Content-Type: application/json' \
  -d '{"reason":"family"}'
```

**Expect:** `200`, `status: cancelled`, `cancelled_at` set (noon on 2026-03-10 in +07).  
`notified_as` still shows the original T1 / R1 / 15:00 / booked snapshot — cancel must **not** rewrite it.

```bash
curl -s -w "\nHTTP %{http_code}\n" -X POST http://127.0.0.1:8000/lessons \
  -H 'Content-Type: application/json' \
  -d '{"date":"2026-03-07","start_time":"15:00","duration_min":60,"student":"Fill In","tutor_id":"T1","room":"R1"}'
```

**Expect:** `201` — the slot is free.

```bash
curl -s -w "\nHTTP %{http_code}\n" -X POST http://127.0.0.1:8000/lessons/L030/cancel \
  -H 'Content-Type: application/json' \
  -d '{"reason":"family"}'
```

**Expect:** `409` already cancelled.

```bash
curl -s -w "\nHTTP %{http_code}\n" -X POST http://127.0.0.1:8000/lessons/L999/cancel \
  -H 'Content-Type: application/json' \
  -d '{"reason":"family"}'
```

**Expect:** `404`.

Tutor-sick style (no 4-hour family late tag):

```bash
curl -s -X POST http://127.0.0.1:8000/lessons/L031/cancel \
  -H 'Content-Type: application/json' \
  -d '{"reason":"tutor"}'
```

**Expect:** note contains `cancelled:tutor` (not the family late/free rule).

Late vs free on the pinned clock: “now” is **noon 10 Mar**. A family cancel of a **10 Mar 09:00** lesson is in the past (`hours_before` negative) → tagged `;free`. A family cancel of a **10 Mar 15:00** lesson is 3 hours before start → `;late`. There is no 10 Mar 15:00 row in seed; create one first if you want to see `;late`.

---

## 10. Demo POSTs vanish on restart

1. Run 6a (create L035).  
2. `GET /lessons?date=2026-03-10` — L035 is there.  
3. Restart uvicorn.  
4. `GET /lessons?date=2026-03-10` — only L033 and L034 again.

**Expect:** seed reload. Fine for the take-home; say it before they ask.

---

## Suggested live-demo order (interview)

1. `/health` — pinned date  
2. `/conflicts` — L007/L008, L033/L034, Friday cap, L032; L009/L010 absent  
3. POST T1 10 Mar 09:00 → **409**  
4. POST T2 R3 10 Mar 09:00 → **201**  
5. One sentence: cap and Monday are visible, not blockers; exam pair is the exception to “one lesson per room”