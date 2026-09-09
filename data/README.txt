Export taken from the front-desk spreadsheet on 2026-03-10, then tidied by us
before it reached you.

One row per lesson, one lesson_id per row. Dates are ISO (YYYY-MM-DD), times
are 24-hour local, duration_min is a whole number of minutes, and tutor_id
joins to tutors.csv. status is one of booked, cancelled, no_show. cancelled_at
is set only on cancelled rows. Every row parses and every identifier resolves;
there is nothing here you need to repair first.

What the rows describe is a different matter. They are what the centre
actually ran that week, which is not always what the rules say should have
happened.
