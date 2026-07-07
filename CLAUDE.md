# task-log

Terminal viewer for registered time entries, sourced from Redmine, built with Textual. Personal single-user tool for attila.hogyai@brickztech.com.

## Run it

```
uv run python main.py
```

Reads `./config.toml` (cwd-relative, hardcoded in `main.py`). Real credentials live only in `config.toml`, which is gitignored — `config.example.toml` is the checked-in template.

## Architecture

```
task_log/
├── models.py       TimeEntry dataclass (id, spent_on, hours, project, issue_id,
│                   issue_subject, user, activity, comments)
├── datasource.py   DataSource Protocol: list_time_entries() -> list[TimeEntry]
│                   This is the swap-later abstraction — UI code only depends on this.
├── config.py       tomllib-based config loader -> AppConfig(backend, redmine=RedmineConfig)
├── factory.py      build_datasource(cfg) -> DataSource; one if/elif on cfg.backend.
│                   Adding a second backend = new class + one elif line, nothing else.
├── redmine/
│   └── client.py   RedmineClient: session-cookie login + CSV fetch + parse (see below)
└── ui/
    ├── app.py            TaskLogApp: loads config, builds datasource via factory, pushes screen
    ├── screens.py        TimeEntriesScreen: user-filter Select bar + (list DataTable | calendar
    │                     view) in a ContentSwitcher. Calendar view = MonthCalendar with a
    │                     "#day-entries" DataTable below it showing the entries of the
    │                     cursor-highlighted day (driven by the MonthCalendar.DaySelected message).
    │                     The user filter is global: _apply_filter() feeds the same filtered list
    │                     to the list table, the calendar, and the day panel; options are rebuilt
    │                     from the fetched data on each refresh (selection preserved if the user
    │                     still exists, else resets to All users). Keys: "r" refresh, "v" toggle
    │                     list/calendar, "u" focus user filter, and (calendar view only, hidden
    │                     from footer otherwise via check_action) "p"/"n" prev/next month,
    │                     "t" jump to today. No pagination — DataTable scrolls locally.
    └── calendar_view.py  MonthCalendar(DataTable): month grid, one cell per day showing
                          total hours + entry count ("8.5h · 2"). Posts DaySelected(day) as the
                          cursor moves; rebuilds keep the cursor on the previously selected day
                          when visible, else on today. Rebuilt from the full entry list on
                          set_entries()/month change — no extra fetches.
```

UI code never imports `requests` or `RedmineClient` — only `DataSource`/`TimeEntry`.

## How Redmine access actually works (important — don't re-derive this)

The user's original request assumed `/projects/brickz/time_entries?page=1` was JS-rendered
and would need a headless browser + DOM parsing. **That assumption turned out to be wrong**
after live testing against `https://support.swicon.com`:

- `time_entries.json` (the natural REST API choice) returns **401** with
  `WWW-Authenticate: Basic realm="Redmine API"` — this instance's REST API only accepts an
  API key / Basic auth, not the session cookie. Session-authenticated JSON requests are
  blocked outright. Do not retry this path without an API key.
- The plain HTML page (`/projects/brickz/time_entries?page=N`) is actually fully
  server-rendered — all rows are already in the HTML returned by a plain `requests.get`
  with the session cookie. No JavaScript execution needed. **Playwright/headless-browser
  approach is unnecessary here** — it was in the original plan but dropped once this was
  confirmed.
- The CSV export (`/projects/brickz/time_entries.csv`) also works with the session cookie
  (it's a regular web-UI export action, not gated behind the REST API check) and returns
  **all** matching entries in a single response — it does **not** honor `?page=` or
  `?offset=`/`limit=` params; it always dumps the full result set for the current
  project/filter. This is what `RedmineClient.list_time_entries()` uses. It was 44 rows
  at the time this was built — if the project's entry count grows into the thousands,
  revisit whether one full CSV pull per refresh is still fine, or whether date-range
  filtering (Redmine CSV export supports query params like `spent_on` filters via the
  standard `f[]`/`op[]`/`v[]` query filter syntax) should be added.
- CSV response encoding is **not UTF-8** — the server returns it without a charset, and
  `requests` defaults to `ISO-8859-1`. `RedmineClient` explicitly decodes with `cp1250`
  (confirmed correct for Hungarian text/comments in this data). If a future user/locale
  breaks on encoding, check `resp.apparent_encoding` again — don't assume UTF-8.
- Login: plain Rails-style session login. GET `/login`, regex-scrape
  `authenticity_token` from `<input name="authenticity_token" value="...">`, POST
  `{authenticity_token, back_url, username, password, login: "Login"}` to `/login`.
  Success is detected by checking the post-login response isn't still a login page
  (checks `/login` not in `resp.url` and `"login-form"` not in the response body).
  The CSRF token is per-session and expires — never hardcode one.
- `TimeEntry.id` is a **synthetic row index**, not a real Redmine entry ID — the CSV
  export doesn't include one. Fine for display; don't build edit/delete-by-id features
  on top of it without first finding a real ID source (e.g. re-adding the `.json`/HTML
  path just for ID lookup, or an API key for REST access).
- Issue column in the CSV looks like `Task #30568: Lupus - AMS` (tracker name varies:
  Task/Bug/Feature/Support/...). `RedmineClient._parse_issue` extracts id/subject via
  `#(\d+):\s*(.*)$` — tracker-name-agnostic. Empty issue field (some time entries aren't
  tied to an issue) parses to `(None, None)`.

## Error handling (intentionally minimal)

- Login failure -> `RedmineLoginError`, caught in `TimeEntriesScreen._load_entries`,
  shown via `self.notify(..., severity="error")`. No retries.
- Network errors (timeout, DNS failure, etc.) -> same catch-all in `_load_entries`.
- `timeout=10` on every `requests` call.
- Verified live: wrong password and unreachable host both produce a clean error
  notification, not a crash. (Note: config-loading errors in `TaskLogApp.on_mount`
  itself — e.g. missing/malformed `config.toml` — are **not** currently wrapped in
  try/except and would crash the app. Not yet smoke-tested; consider wrapping if this
  becomes annoying in practice.)

## Possible next steps (not built, not asked for yet)

- A second `DataSource` backend (e.g. Jira) — mechanically just a new class + factory
  `elif`, per the design.
- Filtering (date range, by user, by issue) — would need Redmine's CSV query-filter
  params (`f[]=spent_on&op[]=...&v[]=...`) since there's no client-side filtering yet.
- If entry volume grows large, reconsider the "pull everything every refresh" CSV
  strategy — either date-scoped CSV requests or falling back to the paginated HTML page
  scrape (which does support `?page=N` server-side, unlike CSV).
