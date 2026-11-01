---
module: staff
feature: attendance
version: 1
language: en
updated_at: 2026-07-23
status: shipped
---

# Staff Attendance

## Overview

Track daily attendance at **Management → Staff → Attendance** tab. Mark each staff member **Present, Absent, Half Day, or Leave** per date, with optional check-in/check-out times and notes. A monthly view shows the records and per-status counts.

## Workflow

1. Staff page → **Attendance** tab.
2. **Mark attendance** — pick the staff member, date, status (Present / Absent / Half Day / Leave), and optional notes; save.
3. Browse months with the previous/this/next month navigator; the table lists entries with per-staff counts.
4. Edit or delete an entry if marked wrongly.

## Business rules

- One entry per staff member per day — marking again the same day is rejected ("Attendance record already exists for this staff member on this date").
- Entries are one-at-a-time (staff + date); there's no bulk "mark all present" yet.
- Check-out must be after check-in; an open check-in on another day must be closed first.
- Attendance is managed by the **owner** — staff cannot mark their own attendance.
- The staff member must be active and assigned to the selected store.
- Requires an active staff list (paid plan with the staff feature).

## Examples

- "Ramesh aaj half day tha" → Attendance → Ramesh → today → Half Day → save.
- "Is month kitne din present?" → monthly summary counts per staff.
- "Galat mark ho gaya" → edit the entry's status.

## Errors

- "Attendance record already exists for this staff member on this date" — edit the existing entry instead.
- "Staff member not found or not assigned to this store".
- "checkOut must be after checkIn".
- "No active staff" — invite staff first.

## FAQ

**Q: Can staff self-mark attendance?** 
No — the owner marks attendance today.

**Q: Is there a calendar view?** 
The current view is a month navigator with a table and counts, not a calendar grid.

**Q: Does attendance affect salary automatically?** 
Not automatically — but when paying salary, DragBizz warns if the pay period has no attendance records so you can double-check.
