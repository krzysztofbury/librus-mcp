# MCP response contract

This is the current, backward-compatible response shape. The server returns its
existing text content, and the MCP SDK also validates and advertises typed
`outputSchema` and `structuredContent`. Pydantic models live in
`src/output_models.py`; the `uv.lock`-pinned `mcp` SDK generates the published
JSON schemas from the return annotations in `src/server.py`.

## Catalog measurement

Run `uv run python release_verification/measure_tools.py` and add
`--all-features` to list optional tools too. Both commands start the real MCP
server over stdio with synthetic credentials. They measure the UTF-8 bytes of
the `tools/list` result serialized with `by_alias=True, exclude_unset=True`,
including descriptions, input schemas, output schemas, and annotations. They do
not contact Librus or invoke tools that consume read-once events or send messages.

| Profile | Tools | Before typing | Before shortening | Current | Typed output schemas | Context budget |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Default | 22 | 16,728 B | 32,219 B | 31,732 B | 22 | 48 KiB |
| All feature gates enabled | 26 | 20,763 B | 38,981 B | 37,729 B | 26 | 64 KiB |

Measurements use the `uv.lock` dependency set. The before-typing and default
before-shortening values were recorded on 2026-09-27; the all-features
before-shortening and both current values were measured on 2026-09-29.
The before-typing and before-shortening columns describe the earlier 21/25-tool
catalog; the current 22/26-tool catalog includes `get_completed_lessons_page`.
Default gates include notifications and attachments; behaviour notes and
sending messages require opt-in. The CI budget guards total catalog growth,
not the exact bytes of every SDK-generated schema.
The reviewed full catalog schema/annotation snapshot lives in
`tests/snapshots/tool_contracts_all.json`. Refresh it with
`uv run python release_verification/measure_tools.py --contracts --all-features`
and review changes before accepting them. The stdio test also verifies the
default feature gates against that same snapshot. Prose descriptions are
excluded from the snapshot so they can be improved independently; the measured
byte budgets still include them.
The clean installed-wheel check also exercises `tools/list` and `list_students`
over stdio on Linux, macOS and Windows, without contacting Librus.

## Output shapes

The table describes `structuredContent` at the top level. Text blocks retain
their earlier serialization. For top-level arrays the SDK adds a `result` key
in `structuredContent`; this is not a new envelope in the text content.

| Tool | Current fields or collection item shape |
| --- | --- |
| `list_students` | `result`: list of account aliases. |
| `get_grades` | `numeric`: list of per-semester maps from subject to grade rows; `gpa`: subject map of `{semester, gpa, subject}` rows; `descriptive`: list of per-semester maps from subject to descriptive grade rows. Grade rows retain title, grade, counts, date, href, desc, semester, category, teacher and weight. GPA can be a number or `"-"`. |
| `get_messages` | `messages`: rows with author, title, date, href, unread and has_attachment; `folder`, `truncated`. A one-page result also has `page` and `max_page` (null for sent messages); legacy `all_pages` instead has `pages_fetched`. Bounded results also include `offset`, `pages_fetched`, `next_page` and `next_offset` (both null at the end or when continuation is unsafe). Missing keys in legacy results remain missing. |
| `get_message_content` | Required author, title, date and content. |
| `get_attendance` | `result`: list of semester lists. Entries include symbol, href, semester, date, type, teacher, period, excursion, topic and subject. |
| `get_attendance_detail` | Map of upstream Polish label to string value. |
| `get_attendance_frequency` | Required first_semester, second_semester and overall ratios (0 to 1). |
| `get_subject_frequency` | Map of subject to percentage (0 to 100). |
| `get_homework` | `result`: rows with lesson, teacher, subject, category, task_date, completion_date and href. |
| `get_homework_detail` | Map of upstream Polish label to string value. |
| `get_schedule` | Map of day number to event rows. JSON day keys are strings; event rows include title, subject, data, day, number, hour and href. |
| `get_schedule_detail` | Map of upstream Polish label to string value. |
| `get_timetable` | `result`: seven weekday lists of periods. A period retains subject, teacher_and_classroom, date, date_from, date_to, weekday, info, number and nullable recess times. Split groups remain joined inside the subject and teacher fields. |
| `get_announcements` | `result`: title, author, description and date per announcement. |
| `get_completed_lessons` | `result`: subject, teacher, topic, z_value, attendance_symbol, attendance_href, lesson_number, weekday and date per lesson. |
| `get_completed_lessons_page` | `lessons`: same row shape; `page`, `offset`, `max_page`, `pages_fetched`, nullable `next_page` and `next_offset`, and `truncated`. This is a separate tool so the legacy list response does not change. |
| `get_student_information` | name, class_name, number, tutor, school and lucky_number (number or `"?"`). |
| `get_final_grades` | `result`: subject, midterm, predicted_final and final per subject; `"-"` means not issued. |
| `get_recent_schedule_events` | `result`: date_added, type and data per event. This consumes a read-once upstream view and checkpoints it locally. |
| `get_new_notifications` | `first_run` and `new`, containing grade, attendance, message, announcement, schedule and homework lists. Reading updates local seen state. |
| `get_message_attachments` | `result`: filename, message_id and file_id per attachment. |
| `download_attachment` | path, filename, size in bytes and content_type. The path is local to the server. |
| `get_behaviour_notes` | `result`: date, teacher, category and content per note. Experimental and disabled by default. |
| `get_recipient_groups` | `result`: list of group IDs. |
| `get_recipients` | Map of recipient name to recipient ID. |
| `send_message` | Discriminated non-error schema: preview (`confirmation_required`) includes `confirm_token`, `expires_in_seconds` and the exact `preview` payload; delivery (`sent` or `failed`) includes `success`, upstream `result`, `title` and `recipient_count`. Existing text JSON is unchanged. Uncertain delivery remains `isError=true` with no `structuredContent`: output schemas only describe non-error tool results. Check the sent folder before considering another attempt; never blindly retry. This write tool remains disabled by default. |

## Input schemas and annotations

`list_students` has no arguments. All other tools require a `student_alias` of
1 to 80 printable characters without surrounding whitespace. Tool arguments
are validated by the MCP SDK and again by the client wrapper where necessary:

- Grade and attendance list tools accept `sort_by` as `all`, `week`, or
  `last_login`; it filters changes rather than sorting them.
- `get_messages` accepts `page` from 0 to 1000 and `folder` as `received` or
  `sent`. With `limit` (1 to 2000), `max_pages` (1 to 40), or `offset` (0 to 49),
  it returns a bounded batch with a best-effort `(next_page, next_offset)` cursor.
  When only one bound is given, the other defaults to its existing hard cap.
  Use the returned pair as the next `page` and `offset`; the cursor is not a
  snapshot. A full last sent page can yield a speculative next cursor that
  repeats rows across requests; consumers should compare message IDs.
  `all_pages` stays available
  for old clients but cannot be combined with bounds or an offset. Multi-page
  message reads have a 120-second whole-operation deadline; completed lessons
  have a 180-second deadline. Timeout is an error, not a partial result.
  Message, attachment, homework and
  attendance detail IDs are bare numeric strings.
- Homework and completed lessons use `date_from` and `date_to` in YYYY-MM-DD
  form. `get_completed_lessons_page` accepts `page` (0 to 99), `offset` (0 to
  9999), `limit` (1 to 1000, default 100) and `max_pages` (1 to 10, default 1).
  Return the next pair with the same dates to continue, or stop when both are
  null. The older `get_completed_lessons` keeps its list shape, and both paths
  reject date ranges with more than 100 upstream pages. A moving range is not
  a stable snapshot. Timetable uses a Monday date. Subject frequency accepts optional
  `start` and `end`. Calendar inputs use a four-digit year and one- or
  two-digit month; schedule detail takes a validated relative event href.
- `send_message` requires a non-empty title, content and 1 to 50 unique
  numeric recipient IDs. The schema caps title at 200 characters, content at
  15,000 and each ID at 20; runtime also caps the combined UTF-8 payload at
  64 KiB. The tool remains opt-in and requires a confirmation token to send.

Read tools are annotated read-only and non-destructive. `get_new_notifications`,
`get_recent_schedule_events` and `download_attachment` have `readOnlyHint=false`
and `idempotentHint=false` because they update local state or consume a
read-once upstream view. `send_message` has `destructiveHint=true` and
`idempotentHint=false` because it delivers a real school message. These
annotations are hints to MCP hosts, not a substitute for runtime validation.

These models describe current data rather than introducing new field names,
pagination envelopes or normalized Polish labels. Unknown fields on upstream
records are preserved in structured results. The full per-tool
input/output/annotation snapshot still needs separate review.
