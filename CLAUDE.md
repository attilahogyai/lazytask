# task-log

Terminal viewer for registered time entries, sourced from Redmine, built with Textual. Personal single-user tool for attila.hogyai@brickztech.com.

## Run it

```
uv run python main.py
```

## Tests

```
uv run pytest
```

`tests/` drives real `TimeEntriesScreen`/`EditEntryScreen` UI via Textual's
`App.run_test()` Pilot (real keypresses, real widget state) against a
`FakeDataSource` (`tests/fakes.py`, in-memory `DataSource` implementation) —
no network calls, no `config.toml` needed. Add new UI-behavior regression
tests the same way rather than unit-testing internals directly.

Reads `./config.toml` (cwd-relative, hardcoded in `main.py`). Real credentials live only in `config.toml`, which is gitignored — `config.example.toml` is the checked-in template.

## Architecture

```
task_log/
├── models.py       TimeEntry dataclass (id, spent_on, hours, project, project_id,
│                   issue_id, issue_subject, user, user_id, activity, activity_id,
│                   comments) — id/project_id/activity_id/user_id are real Redmine
│                   numeric ids, sourced straight from the JSON API responses.
│                   Also Activity(id, name, is_default) and Project(id, name) for
│                   dropdown options; is_default flags the activity Redmine's own web
│                   UI pre-selects when logging a new entry (used the same way here).
├── datasource.py   DataSource Protocol: list_time_entries() -> list[TimeEntry],
│                   list_activities() -> list[Activity], list_projects() -> list[Project],
│                   current_user_id() -> int, update_time_entry(entry_id, *, project_id,
│                   spent_on, hours, issue_id, activity_id, comments) -> None,
│                   create_time_entry(*, project_id, spent_on, hours, issue_id,
│                   activity_id, comments) -> None (same fields, no entry_id).
│                   This is the swap-later abstraction — UI code only depends on this.
├── config.py       tomllib-based config loader -> AppConfig(backend, redmine=RedmineConfig).
│                   RedmineConfig is (base_url, project_identifier, api_key).
├── factory.py      build_datasource(cfg) -> DataSource; one if/elif on cfg.backend.
│                   Adding a second backend = new class + one elif line, nothing else.
├── day_flags.py    DayFlagStore: local, backend-independent per-day flags (vacation, etc.) —
│                   these are NOT a Redmine concept and never touch DataSource/RedmineClient.
│                   Persisted as JSON (day.isoformat() -> [flag, ...]) at a path passed to the
│                   constructor; loaded eagerly, saved on every toggle(). Real usage defaults
│                   to ./day_flags.json (gitignored, cwd-relative like config.toml — see
│                   TimeEntriesScreen.__init__ in screens.py). FLAG_STYLES maps a flag name to
│                   a Rich style string used as the calendar cell's background (currently just
│                   VACATION -> "on dark_green"); add a new flag kind by adding one entry here
│                   plus one entry in screens.py's _FLAG_KEYS.
├── redmine/
│   └── client.py   RedmineClient: pure REST JSON API access via an API key (see below)
└── ui/
    ├── app.py            TaskLogApp: loads config, builds datasource via factory, pushes screen
    ├── screens.py        TimeEntriesScreen: a "#filters" Horizontal bar with user-filter and
    │                     issue-filter Select widgets side by side, above (list DataTable |
    │                     calendar view) in a ContentSwitcher. Calendar view = MonthCalendar
    │                     with a "#day-entries" DataTable below it showing the entries of the
    │                     cursor-highlighted day (driven by the MonthCalendar.DaySelected message).
    │                     Both filters are global and combine with AND: _apply_filter() feeds the
    │                     same filtered list to the list table, the calendar, and the day panel;
    │                     options for both are rebuilt from the fetched data on each refresh
    │                     (selection preserved if the user/issue still exists, else resets to
    │                     "All"). Keys: "r" refresh, "v" toggle list/calendar, "u" focus user
    │                     filter, "i" focus issue filter, "e" edit the entry under the cursor
    │                     (list row or day-entries row — see below), "a" add a new entry
    │                     (pre-filling its issue field from the active issue filter, if any —
    │                     see edit_screen.py), and (calendar view only, hidden from footer
    │                     otherwise via check_action) "p"/"n" prev/next month, "t" jump to
    │                     today, "f" arms flag mode on the cursor-highlighted day. No
    │                     pagination — DataTable scrolls locally.
    │                     Flag mode ("f" then a second key, calendar view only): action_flag_day
    │                     sets self._flag_pending=True and notifies; the screen's own on_key
    │                     override intercepts the *next* key event and calls event.stop() before
    │                     it can bubble to App and trigger a normal binding (this is why plain
    │                     "v" still toggles list/calendar — on_key only swallows a key while
    │                     _flag_pending is True, and always resets it first). "v" maps to
    │                     VACATION via _FLAG_KEYS; DayFlagStore.toggle() flips it and the result
    │                     is pushed to MonthCalendar.set_flags() to re-render. Any key other
    │                     than one in _FLAG_KEYS just cancels flag mode (falls through
    │                     unstopped, so e.g. "f" then "r" still refreshes).
    ├── edit_screen.py    EditEntryScreen(ModalScreen[bool]): form with project/activity Select
    │                     dropdowns and date/hours/issue/comments Input fields. Doubles as both
    │                     the edit and add-new form: constructed with an existing TimeEntry to
    │                     pre-fill and call datasource.update_time_entry(...) on save, or with
    │                     entry=None to show blank/defaulted fields (today, first project, the
    │                     is_default activity, and — via the optional default_issue_id
    │                     constructor arg — the screen's active issue filter, if any) and call
    │                     datasource.create_time_entry(...) instead. default_issue_id is ignored
    │                     when entry is not None (editing always shows the entry's own issue).
    │                     dismiss(True) on success triggers a list refresh via the push_screen
    │                     callback (TimeEntriesScreen.action_edit_entry /
    │                     action_add_entry both use the same _on_edit_result callback),
    │                     dismiss(False) on cancel.
    └── calendar_view.py  MonthCalendar(DataTable): month grid, one cell per day showing
                          total hours + entry count ("8.5h · 2"). Posts DaySelected(day) as the
                          cursor moves; rebuilds keep the cursor on the previously selected day
                          when visible, else on today. Rebuilt from the full entry list on
                          set_entries()/month change — no extra fetches. set_flags(dict[date,
                          frozenset[str]]) stores flags from DayFlagStore and rebuilds; a
                          flagged day's cell Text is built with its FLAG_STYLES background set
                          as the Text's base `style` (Rich composes this under the day-number/
                          hours spans' own foreground styles — see day_flags.py), then both
                          lines are manually padded to the column's inner content width so the
                          background fills the whole cell rather than just the glyphs
                          (DataTable/Rich don't auto-pad a short Text to its column width).
```

UI code never imports `requests` or `RedmineClient` — only `DataSource`/`TimeEntry`.

## How Redmine access actually works (important — don't re-derive this)

The user's original request assumed `/projects/brickz/time_entries?page=1` was JS-rendered
and would need a headless browser + DOM parsing. That assumption turned out to be wrong —
the plain HTML page is fully server-rendered — but that path is now moot anyway, since
the app has since switched entirely to Redmine's **REST JSON API with an API key**
(needed once editing was added, since editing requires real entry/project/activity ids
that the old CSV export never provided). Confirmed live against
`https://support.swicon.com` on 2026-07-07:

- Earlier testing (before an API key was available) found `time_entries.json` returns
  **401** with `WWW-Authenticate: Basic realm="Redmine API"` when hit with only a session
  cookie. **That 401 was not a sign the REST API is unusable** — it was simply hit
  without any credentials the API accepts. Once a real API key is sent via the
  `X-Redmine-API-Key` header, all of `time_entries.json`, `issues.json`,
  `enumerations/time_entry_activities.json`, `projects.json`, `users/current.json`, and
  `PUT time_entries/{id}.json` return clean 200s (204 for the PUT). If this ever
  regresses to a 401, suspect a revoked/rotated key or REST API access having been
  toggled off instance-wide (Administration → Settings → API, admin-only) — not that the
  API itself is gone.
- `RedmineClient` sets `X-Redmine-API-Key` once on `self._session.headers` in `__init__`
  — no login flow, no session cookie, no CSRF token anywhere. Redmine skips CSRF
  verification entirely for API-key-authenticated requests.
- `list_time_entries()` hits `GET {base_url}/projects/{project_identifier}/time_entries.json`,
  paginated via `limit=100`/`offset=N` in a loop against the response's `total_count` —
  unlike the old CSV export, this actually scales past the current ~44 rows.
- **Non-obvious and easy to re-break:** the `issue` field on a time entry from this
  endpoint is `{"id": N}` only — **no subject text**. Getting the Issue column's subject
  requires a second batch call: `GET {base_url}/issues.json?issue_id=<comma-joined ids>&status_id=*`.
  `status_id=*` is required — without it, closed issues are silently excluded from the
  response and their time entries show a blank subject (this is not a 404 or error, it
  just silently omits the issue from `issues`, so it's easy to miss in testing if you
  only test against open issues). `_fetch_issue_subjects` batches this in chunks of
  ≤100 ids to stay under Redmine's `issue_id=` filter limits, and entries take one
  combined call rather than one call per entry.
- `list_activities()` hits `GET {base_url}/enumerations/time_entry_activities.json`
  (global list, not project-scoped) and caches the result for the client's lifetime.
- `list_projects()` hits `GET {base_url}/projects.json` (paginated like time entries) and
  caches the result. For this account it currently returns exactly one project (Brickz,
  id 90) — the API key's user only has access to that project — so the edit form's
  project dropdown will only ever show one option in practice, even though it's wired up
  generically.
- `current_user_id()` hits `GET {base_url}/users/current.json` and caches the result —
  used to restrict editing to the logged-in user's own entries (`TimeEntriesScreen.action_edit_entry`
  checks `entry.user_id == datasource.current_user_id()` client-side before opening the
  edit modal; Redmine's own permission model would also reject a cross-user edit
  server-side, but the client-side check avoids a doomed round trip).
- `update_time_entry(...)` does `PUT {base_url}/time_entries/{id}.json` with a JSON body
  `{"time_entry": {...}}`. **A successful edit returns `204 No Content`, not `200`** —
  don't try to parse a body on success. `issue_id` is sent explicitly as `null` (not
  omitted) when clearing an issue, since Redmine only clears a field when the key is
  present with a null value. On 401/403 → `RedmineAuthError`; on 422 → `RedmineUpdateError`
  built from the JSON body's `errors` list (Redmine's validation-error format); on 404 →
  `RedmineUpdateError` (entry deleted elsewhere since the list was loaded).
- `create_time_entry(...)` does `POST {base_url}/time_entries.json` with the same
  `{"time_entry": {...}}` shape (minus an id) and shares the same 401/403/422 handling
  via `RedmineClient._raise_for_write_errors`. A new entry is always logged under the
  API key's own user — Redmine only lets a request set a different `user_id` with the
  "manage all entries" permission, not needed for this personal single-user tool, so
  `user_id` is never sent.
- All JSON responses are pure UTF-8 per spec — the old CSV-specific `cp1250` decoding
  workaround is gone entirely along with the CSV path; Hungarian text now round-trips
  correctly with no special handling.
- The old session-cookie login flow, CSRF-token scraping, and CSV parsing
  (`_ensure_login`, `_scrape_csrf_token`, `_parse_csv`, `_parse_issue`, `RedmineLoginError`)
  were deleted on 2026-07-07 once the API-key path was verified live end-to-end (see git
  history for the removed code if this path ever needs to be resurrected — e.g. if the
  API key is ever revoked and only a username/password remains available).
- Issue subjects/tracker names (e.g. `Task #30568: Lupus - AMS`) are now assembled by the
  UI from `issue_id` + `issue_subject` directly (`f"#{e.issue_id}: {e.issue_subject}"` in
  `screens.py`), not parsed out of a combined string — the tracker name (Task/Bug/etc.)
  is no longer available at all via this API shape and is simply dropped from display.

## Error handling (intentionally minimal)

- Auth/permission failures -> `RedmineAuthError`, update validation/not-found failures ->
  `RedmineUpdateError` (both subclass `RedmineApiError(RuntimeError)`), caught in
  `TimeEntriesScreen._load_entries`/`action_edit_entry` and `EditEntryScreen._save`,
  shown via `self.notify(..., severity="error"/"warning")`. No retries.
- Network errors (timeout, DNS failure, etc.) -> same catch-all pattern.
- `timeout=10` on every `requests` call.
- Verified live: wrong/missing API key produces a clean 401 caught as `RedmineAuthError`,
  not a crash. (Note: config-loading errors in `TaskLogApp.on_mount` itself — e.g.
  missing/malformed `config.toml` — are **not** currently wrapped in try/except and would
  crash the app. Not yet smoke-tested; consider wrapping if this becomes annoying in
  practice.)

## Possible next steps (not built, not asked for yet)

- A second `DataSource` backend (e.g. Jira) — mechanically just a new class + factory
  `elif`, per the design.
- Filtering (date range, by user, by issue) — Redmine's JSON API supports the same
  `f[]=spent_on&op[]=...&v[]=...` query-filter syntax the CSV export did; not wired up
  client-side yet since there's no client-side filtering beyond the user dropdown.
- Deleting time entries — `DELETE {base_url}/time_entries/{id}.json` would follow the
  same auth/error pattern as `update_time_entry`; not built since it wasn't asked for.
- Logging a new entry against a different user — would need the "manage all entries"
  Redmine permission and a user-picker in `EditEntryScreen`; not built, low value for a
  single-user tool.
