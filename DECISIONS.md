# Decisions (interview notes)

This document is the talking script for an in-person review. It records what we built, what we refused to guess, and where the brief disagrees with itself. The product is a **local FastAPI + SQLite** booking helper over one exported week. Clock is pinned.

---

## 1. Pinned clock

| Constant | Value | Why |
| --- | --- | --- |
| `TODAY` | `2026-03-10` | Date of the front-desk export (`data/README.txt`) |
| `TIMEZONE` | `Asia/Ho_Chi_Minh` (`+07:00`) | CSV `cancelled_at` offsets are `+07:00` |
| “Now” on cancel | noon on `TODAY` in that zone | Late-cancel needs a datetime; the brief never gives a wall-clock, so noon is an explicit, boring default |

Every “is this late?”, “what is today?”, and `/health` payload uses `TODAY`, never `date.today()`. If a laptop is opened in 2026-09, Friday 6 March still has seven T1 lessons and Tuesday 10 March is still “today”.

Cancel math: `hours_before = lesson_start - noon_on_TODAY`. Family cancel is `late` when `0 <= hours_before < LATE_CANCEL_HOURS` (4). Past lessons get `;free` because `hours_before` is negative — that is a known weakness, not a hidden rule.

`CUTOFF_HOUR = 16` lives in `app/config.py` but is **not applied** anywhere. See “brief argues with itself”.

---

## 2. Centre summary

Bright Path is a small tuition centre. Three tutors (T1 Ngoc Anh Maths, T2 Pham Duc English, T3 Le Thu Physics), three rooms (R1–R3), six named students, lesson lengths **60 or 90** minutes.

Seed week **2026-03-03 (Tue) → 2026-03-10 (Tue)**:

| Date | Weekday | What the sheet shows |
| --- | --- | --- |
| 3 | Tue | Normal morning; L005 family-cancelled early (08:15) so the 14:00 T2/R2 slot is free |
| 4 | Wed | Chau double-booked 09:00 (L007+L008); exam pair L009/L010 in R1 with T1 |
| 5 | Thu | L015 `no_show`; L017 cancelled `tutor sick` at 14:40 for a 16:00 slot |
| 6 | Fri | T1 stacked from 09:00 through 20:30 — **seven** occupying lessons |
| 7 | Sat | Light day |
| 8 | Sun | One lesson (L031) |
| 9 | Mon | L032 Vu Ha My / T3 / R3 — family asked to move off Sunday |
| 10 | Tue | T1 in R1 **and** R2 at 09:00 (L033+L034). This is “today”. |

Statuses: `booked`, `cancelled`, `no_show`. Occupying for clash detection = `{booked, no_show}`. Cancelled rows keep history and the tutor notification snapshot; they do not hold the room.

---

## 3. Questions for the owner (and how answers change the build)

These were not safe to invent. Each one is a fork in the code.

### 3.1 Exam pairs

**Ask:** Are two students in one room with one tutor a single product (half-price exam pair) or a data error? Must they share tutor *and* room *and* start *and* duration? Can a pair be three?

**What we did:** If `note` contains `"exam pair"` (case-insensitive), rows that share `(date, start_time, tutor_id, room)` get a `pair_group_id` (`PAIR001`, …). Same-room overlap is **allowed** only when `_same_pair`. Cap `MAX_PAIR_SIZE = 2` → `pair_too_large`.

**If owner says “pairs are two invoice lines but one occupancy”:** keep `pair_group_id`; maybe emit one calendar block. **If “never share a room”:** drop pairing; L009/L010 become `room_overlap`. **If “three siblings OK”:** raise `MAX_PAIR_SIZE` or key off a staff flag, not note text.

### 3.2 Six-lesson daily cap

**Ask:** Is 6 a hard stop, a payroll warning, or “try not to”? Does `no_show` count? Does a cancelled-same-day slot free a token?

**What we did:** Detect `over_daily_cap` on occupying rows. **Do not** 409 a new booking for cap or for Monday (see `blocking_conflicts_for_new`). Friday 6 March is already illegal in the seed; rejecting *new* work while leaving historical over-cap would be inconsistent theatre. Front desk still *sees* it on `GET /conflicts`.

**If owner says hard stop:** add `over_daily_cap` to the blocker set; POST #8 for T1 on that Friday returns 409. **If no_show does not count:** remove `no_show` from `OCCUPYING_STATUSES` for cap only (room might still be blocked).

### 3.3 Monday closed

**Ask:** Is Monday always closed for cleaning, or was L032 an approved exception? Who may override?

**What we did:** `CENTRE_CLOSED_WEEKDAY = 0`. Occupying Monday lessons → `open_on_closed_day`. New bookings on Monday are **not** auto-rejected, because the seed already contains an explicit family move. Reporting without silent delete.

**If “never book Monday”:** add `open_on_closed_day` to blockers; consider a manager override flag. **If “cleaning is R1+R2 only”:** scope the check by room.

### 3.4 16:00 cutoff — source of truth

**Ask:** What is the cutoff? (a) last lesson must *start* before 16:00, (b) last lesson must *end* by 16:00, (c) front desk stops taking *new* bookings after 16:00, (d) late-cancel window is “before 16:00 the day before”, (e) something from a different product?

**What we did:** Stored `CUTOFF_HOUR = 16` as a named constant and **did not enforce it**. Late cancel uses **4 hours before start**, not 16:00. Seed has many legal 16:00 / 17:30 / 19:00 / 20:30 starts (L012, L017, L024–L027). Enforcing “no start at/after 16:00” would mark a third of Friday as invalid and fight the sheet.

**If (a) or (b):** add `after_cutoff` and decide whether seed is exempt. **If (c):** apply only on `POST /lessons` using pinned noon-or-better “now”. **If (d):** replace `LATE_CANCEL_HOURS` with “before 16:00 previous local day”.

### 3.5 L017 tutor sick

**Ask:** When the tutor cancels, is the student owed a make-up? Does the room free immediately? Should T3’s daily cap / pay still count the hour? Who is notified — student, or was the tutor the one who called in?

**What we did:** Status `cancelled`, `cancelled_at=2026-03-05T14:40:00+07:00`, note `tutor sick`. Slot **does not occupy**. Snapshot `notified_as_json` is **kept** (the tutor was told about 16:00 R3 before they called in). Cancel API currently tags `;family` vs late/free — **tutor-initiated cancel is not a first-class reason** in `CancelRequest` (default `reason="family"`). L017 came from CSV, not from our endpoint.

**If “tutor cancel should notify student and auto-offer make-up”:** that is a workflow, not a UNIQUE constraint — do not fold it into overlap detection. **If “sick still occupies until backfill”:** keep status `booked` with a note, or add `status=held`.

---

## 4. Where the brief argues with itself

1. **“CSV is already clean; do not repair”** vs **“what ran is not what the rules say.”** We load every row as-is and *report* rule breaks. We do not rewrite Chau out of R2, do not move L032 off Monday, do not split T1’s Friday.
2. **One lesson per room** vs **exam pair half-price in the same room.** Pairing is the only way both sentences can be true.
3. **Tutors must not be in two rooms** vs **L033 and L034 on the export date.** Detection, not deletion.
4. **Centre closed Monday** vs **L032 “moved from Sunday at the family’s request.”** Exception exists in production data.
5. **Daily cap 6** vs **seven T1 occupying lessons on 6 March.** Cap is a finding, not a seed-load failure.
6. **16:00 cutoff** vs **evening inventory.** Cannot both be hard rules on this sheet.
7. **“Notify tutors of the calendar”** vs **cancellations after notify.** We snapshot `notified_as_json` at insert and **do not mutate it on cancel**, so you can diff “what we told them” vs “what is true now”.
8. **`no_show` vs cancelled.** One consumed the slot (student absent); the other released it. Treating them the same would let someone book over a no-show that already used the room.

---

## 5. Feature list — why conflict-aware booking

Built:

| Feature | Why |
| --- | --- |
| Seed CSV → SQLite on startup / `python -m app.seed` | Repeatable demo; same clashes every time |
| `GET /health` | Prove pinned date/zone |
| `GET /lessons` (+ optional `?date=`) | Front-desk list |
| `GET /conflicts` | **Detect** what already went wrong this week |
| `POST /lessons` | **Reject new** hard clashes (409 + conflict payload) |
| `POST /lessons/{id}/cancel` | Release occupancy; keep notify snapshot; stamp late/free for family |

**Conflict-aware booking** means two jobs, not one:

1. **Detect** — the week already contains illegal states. A system that only validates *new* rows would look “green” while Chau sits in two rooms.
2. **Reject new** — stop making it worse: student double-book, tutor in two rooms, room stolen from a non-pair, pair larger than 2.

We did **not** auto-resolve (no “delete L008”, no “move T1”). Resolution is a human with the family on the phone.

Daily cap and Monday are **visible** but **not blockers** for POST, because the owner has not said they are hard stops and the seed already violates both.

---

## 6. Data model

### Tutors

`tutor_id` PK, name, subject, phone. Lessons FK to tutors. Unknown `tutor_id` on POST → 404.

### Lessons

One row per student-slot (`lesson_id` L001…). A pair is **two rows**, not one, because invoicing and names are per student.

| Column | Role |
| --- | --- |
| `date`, `start_time`, `duration_min` | Interval; duration CHECK `(60, 90)` |
| `student`, `tutor_id`, `room` | Occupancy dimensions |
| `status` | `booked` / `cancelled` / `no_show` |
| `cancelled_at` | Required iff cancelled (CHECK) |
| `note` | Human text; also how we *discover* exam pairs in seed |
| `pair_group_id` | Derived for seed; optional on POST |
| `notified_as_json` | Frozen copy of tutor/room/when/student/status at insert |

API maps `notified_as_json` → `notified_as` object.

### `pair_group_id`

Exists so room overlap can say “this is the product” without parsing notes at query time. Seed assignment is deterministic: groups of `exam pair` notes sharing slot+tutor+room. POST can send a group id to join an existing pair (then `pair_too_large` if a third student joins).

### `notified_as_json`

Tutors are told a version of the diary. If we overwrite the snapshot on cancel, we cannot answer “what text did they get?”. Cancel updates `status` / `note` / `cancelled_at` only.

### Occupying statuses

`OCCUPYING_STATUSES = {booked, no_show}`. Clash and cap loops skip `cancelled`. L005 (family, morning-of) and L017 (tutor sick) do not collide with anyone. L015 no_show still blocks T2/R2 on 5 Mar 13:00.

---

## 7. Why overlap in Python, not UNIQUE

A UNIQUE `(tutor_id, date, start_time)` or `(room, date, start_time)` would be wrong:

| Case | UNIQUE would do | Reality |
| --- | --- | --- |
| L009 / L010 exam pair | Reject second row | Legal same-room same-tutor |
| 10:30/90 vs 11:30/60 | Allow (different `start_time`) | May overlap in time |
| Cancelled then rebook same start | Reject if unique includes cancelled | Slot should be free |
| Tutor two rooms same start | Could unique on tutor+start | Misses **partial** overlap across 60 vs 90 |
| Cap 7 vs 6 | UNIQUE cannot count | Needs GROUP BY day |
| Monday | UNIQUE cannot know weekday | Needs calendar |

Overlap is `begin_a < end_b and begin_b < end_a` on the same local date (`app/timeutil.intervals_overlap`). End-touching (11:30+60 ending 12:30, next at 12:30) is **not** a clash. L021 (11:30) and L022 (13:00) are fine.

SQLite still enforces PK, FK, duration, and cancelled_at CHECK. Integrity ≠ scheduling.

---

## 8. Conflict kinds (with seed examples)

| Kind | Rule | Block new POST? | Seed |
| --- | --- | --- | --- |
| `student_overlap` | Same student, overlapping intervals, both occupying | Yes | **L007, L008** — Lê Minh Châu, 2026-03-04 09:00, R3 vs R2 |
| `tutor_two_rooms` | Same tutor, **different** rooms, overlap | Yes | **L033, L034** — T1, 2026-03-10 09:00, R1 vs R2 |
| `room_overlap` | Same room, overlap, not `_same_pair` | Yes | None in seed (pair is the only same-room overlap) |
| `pair_too_large` | `pair_group_id` has > 2 distinct lessons | Yes | None in seed |
| `over_daily_cap` | Occupying lessons for tutor+day > 6 | **No** | **T1 on 2026-03-06**: L018, L021, L022, L024, L025, L026, L027 (7) |
| `open_on_closed_day` | Occupying lesson on Monday | **No** | **L032** 2026-03-09 |

Same pair of rows can emit more than one kind (e.g. same student *and* tutor in two rooms).

POST T1 / 2026-03-10 / 09:00 / any room other than a legal pair → 409 via `tutor_two_rooms` and/or `room_overlap`. POST T2 / R3 / 09:00 that Tuesday → 201: T2 is free, R3 is free, student is new.

---

## 9. API table and rejected notify endpoint

| Method | Path | Behaviour |
| --- | --- | --- |
| `GET` | `/health` | `{ok, today, timezone}` pinned |
| `GET` | `/lessons?date=` | All, or one day |
| `GET` | `/conflicts?from=&to=` | Default whole seed week |
| `POST` | `/lessons` | 201 or 409 `{detail, conflicts}`; 404 unknown tutor; 422 bad duration |
| `POST` | `/lessons/{id}/cancel` | 200; 404 missing; 409 already cancelled |

**Rejected: `POST /notify` (or “send diary to tutors”).** Reasons:

- No SMS/email provider in a local take-home; a fake 200 would lie in an interview.
- The interesting problem is **state**: store `notified_as_json` at write time; cancel does not rewrite it; GET lessons already returns `notified_as` for a diff.
- A notify endpoint without delivery, idempotency, or “who is the audience (tutor vs family)?” is a stub that invites a product argument we cannot win from the PDF.

If they want notify next week: diff `notified_as` vs current occupying rows, then send. Do not add a button that sets a boolean `notified=true`.

---

## 10. Seed findings (after load, before any POST)

From `data/lessons_export.csv` as of this build:

1. **L007/L008 student_overlap** — phone-add (`added by phone; family confirmed`) stacked Chau on a slot they already had with T3.
2. **L033/L034 tutor_two_rooms** — export-day diary has T1 starting two rooms at 09:00. Likely two staff edited the sheet.
3. **T1 Friday over_daily_cap** — 09:00, 11:30, 13:00, 16:00, 17:30, 19:00, 20:30. Cap 6; we report, we still load.
4. **L032 open_on_closed_day** — Monday, note admits the Sunday→Monday move.
5. **L009/L010 not a clash** — `PAIR001`, same T1/R1/11:00/90.
6. **L005** cancelled 08:15 for 14:00 same day — occupying false; T2/R2 free that afternoon.
7. **L015 no_show** — still occupies.
8. **L017 tutor sick** — cancelled 1h20 before 16:00; occupying false; 4-hour family-late rule does not apply to this CSV row.
9. **No `room_overlap` and no `pair_too_large`** in the unmodified week.
10. **L021/L022** same student+tutor+room, 11:30 then 13:00 — gap, not overlap.

---

## 11. Assumptions

- One centre, one timezone, no DST issues in March 2026 VN.
- Student identity is the string in `student` (no student id file).
- Rooms are labels R1–R3; no capacity metadata beyond pair=2.
- Seed `note` is trusted enough to detect `"exam pair"`; we do not NLP the rest.
- Touching intervals do not clash.
- `GET /conflicts` is diagnostic; it will keep reporting seed sins until a human cancels/moves rows.
- Startup `load_seed()` **wipes** `lessons` and `tutors`. Demo reproducibility beats persistence. Do not point this at a real file and expect it to survive restart.
- Cancel “now” is noon pinned-today. Not 16:00, not the OS clock.
- POST body duration must be 60 or 90 (Pydantic + SQLite CHECK).

---

## 12. Next week (if they hire)

1. Owner answers on pairs, cap, Monday, cutoff, tutor-sick workflow — then promote those into blockers or drop the unused `CUTOFF_HOUR`.
2. Replace note-parsing with an explicit `lesson_kind=exam_pair` on the sheet.
3. Student table + ids (Unicode names, siblings).
4. Notify as a **diff** against `notified_as_json`, not a fire-and-forget POST.
5. Do not wipe DB on startup; migrate; seed only in a CLI.
6. Tests: overlap matrix, pair exemption, 409 vs 201 cases in the README.
7. Idempotent cancel; tutor vs family cancel reasons.
8. Optional: persist `app.db` outside process, backup before seed.

---

## 13. Weak spots

- `CUTOFF_HOUR` unused — looks like a forgotten rule; it is an **unresolved product question**.
- Cap and Monday not enforced on POST — can look “soft” in interview; we chose consistency with seed.
- Exam pairs keyed off English substring in `note`.
- Cancel clock is fake noon; past lessons cancel as `;free`.
- `load_seed` on every uvicorn start destroys POSTs from the last demo.
- No auth, no concurrency control (read then insert).
- Phone numbers in `tutors.csv` are already masked; still PII-adjacent.
- `on_event("startup")` is FastAPI-legacy; fine for this size.
- No automated tests in-repo unless added later.
- Daily cap counts lesson **rows**, not contact hours (a 90-minute slot counts as 1).

---

## 14. AI honesty

A coding assistant helped scaffold FastAPI/SQLite, conflict loops, and these notes. I (the candidate) am accountable for:

- Pinning **2026-03-10 / Asia/Ho_Chi_Minh** instead of `datetime.now()`
- Treating the CSV as **evidence**, not dirt to auto-clean
- Pair exemption and occupying statuses
- 409 only on hard clashes
- Refusing a fake notify API
- Every number in the seed findings (I can walk L007/L008, T1’s Friday list, L032’s weekday, L033/L034 without reading this file)

If a line in the brief was ambiguous, the assistant was told to **ask or isolate a constant**, not to “just make tests pass” by deleting rows.

---

## 15. Thrown away: auto-clean CSV

We did **not** ship a “tidy the spreadsheet” script that would:

- Drop L008 as duplicate Chau
- Merge L033/L034 onto one room
- Chop T1’s evening on 6 March to satisfy cap 6
- Move L032 back to Sunday
- Rewrite notes into enums
- Infer pairs from “same room” without the exam-pair note (that would hide real double-booking)

Auto-clean would destroy the interview: the interesting week is the **messy** one. `data/README.txt` already says identifiers parse and FKs resolve; the remaining mess is operational. Detection > mutation.

---

## 16. Interview drill (Q&A)

**Q: Why is today 10 March 2026?**  
A: That is the export date. Late cancel and “today” in `/health` must match the sheet, not the laptop.

**Q: Why is L009/L010 not a conflict?**  
A: Notes say exam pair; we assign `PAIR001`; `room_overlap` is skipped when `_same_pair`. Different students, same tutor, same room — `tutor_two_rooms` requires *different* rooms, so that kind does not fire either.

**Q: Prove Chau is double-booked.**  
A: L007 T3/R3 09:00 booked and L008 T2/R2 09:00 booked, same name, 4 March. Kind `student_overlap`.

**Q: Prove T1 cannot be in two rooms this morning.**  
A: L033 R1 and L034 R2, both 10 March 09:00, both booked. POST another T1 09:00 → 409.

**Q: Why can I still POST a 7th lesson for a tutor?**  
A: Cap is reported (`over_daily_cap`) but not in `blocking_conflicts_for_new`. Friday already has 7. I would flip that in one line if the owner says hard stop.

**Q: Why Python overlap, not UNIQUE?**  
A: Pairs, partial intervals, cancelled rows, cap, weekday. UNIQUE is the wrong tool. Walk `intervals_overlap`.

**Q: Does no_show free the room?**  
A: No. Occupying. Cancelled yes.

**Q: What did you do with 16:00?**  
A: Named it, did not enforce. Evening lessons exist. Need the owner’s definition.

**Q: L017?**  
A: Tutor sick, cancelled 14:40 for 16:00, not occupying. Snapshot kept. Product of make-up / student notify is unanswered.

**Q: Why no notify endpoint?**  
A: No channel; snapshot + GET is the honest substitute; a stub 200 is worse.

**Q: Why not fix the CSV?**  
A: The brief says the file is structurally clean and operationally dirty. Fixing it would hide the bugs they asked us to find.

**Q: What happens on server restart?**  
A: Seed reloads; demo POSTs vanish. Acceptable for take-home; wrong for production.

**Q: 409 vs 201 demo?**  
A: T1 10 Mar 09:00 → 409. T2 R3 10 Mar 09:00 → 201.

**Q: Weakest part of your design?**  
A: Product forks (cutoff, Monday, cap) encoded as “detect but don’t block”, plus wiping DB on startup, plus pair detection via note substring.

Walk the code in this order in the room: `config.py` → `timeutil.py` → `conflicts.py` → `seed.assign_exam_pairs` → `POST /lessons` → cancel snapshot comment.
