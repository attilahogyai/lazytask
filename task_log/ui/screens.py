from datetime import date

from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import ContentSwitcher, DataTable, Footer, Header, Select

from task_log.datasource import DataSource
from task_log.models import TimeEntry
from task_log.ui.calendar_view import MonthCalendar
from task_log.ui.edit_screen import EditEntryScreen


class TimeEntriesScreen(Screen):
    AUTO_FOCUS = "#entries"

    CSS = """
    #filters {
        height: auto;
    }
    #user-filter, #issue-filter {
        width: 40;
    }
    #day-entries {
        border: round $accent;
        border-title-align: center;
        height: 1fr;
    }
    """

    BINDINGS = [
        ("r", "refresh_entries", "Refresh"),
        ("v", "toggle_view", "List/Calendar"),
        ("u", "focus_user_filter", "User filter"),
        ("i", "focus_issue_filter", "Issue filter"),
        ("e", "edit_entry", "Edit"),
        ("a", "add_entry", "Add"),
        ("p", "prev_month", "Prev month"),
        ("n", "next_month", "Next month"),
        ("t", "this_month", "This month"),
    ]

    def __init__(self, datasource: DataSource):
        super().__init__()
        self._datasource = datasource
        self._entries = []
        self._filtered_entries = []

    def compose(self):
        yield Header()
        with Horizontal(id="filters"):
            yield Select([], prompt="All users", allow_blank=True, id="user-filter")
            yield Select([], prompt="All issues", allow_blank=True, id="issue-filter")
        with ContentSwitcher(initial="entries", id="views"):
            yield DataTable(id="entries")
            with Vertical(id="calendar-view"):
                yield MonthCalendar(id="calendar")
                yield DataTable(id="day-entries", cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#entries", DataTable)
        table.add_columns("Date", "User", "Activity", "Issue", "Comment", "Hours")
        day_table = self.query_one("#day-entries", DataTable)
        day_table.add_columns("User", "Activity", "Issue", "Comment", "Hours")
        self._load_entries()

    @property
    def _in_calendar(self) -> bool:
        try:
            return self.query_one(ContentSwitcher).current == "calendar-view"
        except Exception:
            return False

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action in ("prev_month", "next_month", "this_month") and not self._in_calendar:
            return False
        return True

    def action_toggle_view(self) -> None:
        switcher = self.query_one(ContentSwitcher)
        if self._in_calendar:
            switcher.current = "entries"
            self.query_one("#entries").focus()
        else:
            switcher.current = "calendar-view"
            self.query_one(MonthCalendar).focus()
        self.refresh_bindings()

    def action_focus_user_filter(self) -> None:
        self.query_one("#user-filter", Select).focus()

    def action_focus_issue_filter(self) -> None:
        self.query_one("#issue-filter", Select).focus()

    def action_prev_month(self) -> None:
        self.query_one(MonthCalendar).move_month(-1)

    def action_next_month(self) -> None:
        self.query_one(MonthCalendar).move_month(1)

    def action_this_month(self) -> None:
        self.query_one(MonthCalendar).goto_today()

    def action_refresh_entries(self) -> None:
        self._load_entries()

    def _entry_under_cursor(self) -> TimeEntry | None:
        if self._in_calendar:
            calendar = self.query_one(MonthCalendar)
            day = calendar.date_at(calendar.cursor_coordinate)
            day_entries = [e for e in self._filtered_entries if e.spent_on == day]
            row = self.query_one("#day-entries", DataTable).cursor_row
            return day_entries[row] if 0 <= row < len(day_entries) else None
        row = self.query_one("#entries", DataTable).cursor_row
        return self._filtered_entries[row] if 0 <= row < len(self._filtered_entries) else None

    def action_edit_entry(self) -> None:
        entry = self._entry_under_cursor()
        if entry is None:
            return
        try:
            own_id = self._datasource.current_user_id()
        except Exception as exc:
            self.notify(f"Failed to check permissions: {exc}", severity="error")
            return
        if entry.user_id != own_id:
            self.notify("You can only edit your own time entries", severity="warning")
            return
        self.app.push_screen(EditEntryScreen(entry, self._datasource), callback=self._on_edit_result)

    def action_add_entry(self) -> None:
        issue_select = self.query_one("#issue-filter", Select)
        default_issue_id = None if issue_select.value is Select.BLANK else issue_select.value
        self.app.push_screen(
            EditEntryScreen(None, self._datasource, default_issue_id=default_issue_id),
            callback=self._on_edit_result,
        )

    def _on_edit_result(self, saved: bool | None) -> None:
        if saved:
            self._load_entries()

    def on_select_changed(self, event: Select.Changed) -> None:
        self._apply_filter()

    def on_month_calendar_day_selected(self, message: MonthCalendar.DaySelected) -> None:
        self._show_day(message.day)

    def _show_day(self, day: date) -> None:
        table = self.query_one("#day-entries", DataTable)
        table.clear()
        day_entries = [e for e in self._filtered_entries if e.spent_on == day]
        for e in day_entries:
            issue = f"#{e.issue_id}: {e.issue_subject}" if e.issue_id else ""
            table.add_row(e.user, e.activity, issue, e.comments, f"{e.hours:g}")
        if day_entries:
            total = sum(e.hours for e in day_entries)
            table.border_title = f"{day.isoformat()} — {total:g}h in {len(day_entries)} entries"
        else:
            table.border_title = f"{day.isoformat()} — no entries"

    def _apply_filter(self) -> None:
        user_select = self.query_one("#user-filter", Select)
        user = None if user_select.value is Select.BLANK else user_select.value
        issue_select = self.query_one("#issue-filter", Select)
        issue_id = None if issue_select.value is Select.BLANK else issue_select.value

        filtered = [
            e
            for e in self._entries
            if (user is None or e.user == user) and (issue_id is None or e.issue_id == issue_id)
        ]
        self._filtered_entries = filtered

        table = self.query_one("#entries", DataTable)
        table.clear()
        for e in filtered:
            issue = f"#{e.issue_id}: {e.issue_subject}" if e.issue_id else ""
            table.add_row(e.spent_on.isoformat(), e.user, e.activity, issue, e.comments, f"{e.hours:g}")
        self.query_one(MonthCalendar).set_entries(filtered)

        labels = [user] if user is not None else []
        if issue_id is not None:
            labels.append(f"#{issue_id}")
        if labels:
            self.sub_title = f"{' & '.join(labels)}: {len(filtered)} of {len(self._entries)} entries"
        else:
            self.sub_title = f"{len(filtered)} entries"

    def _load_entries(self) -> None:
        try:
            entries = self._datasource.list_time_entries()
        except Exception as exc:
            self.notify(f"Failed to load entries: {exc}", severity="error")
            return
        self._entries = entries

        user_select = self.query_one("#user-filter", Select)
        previous_user = user_select.value
        users = sorted({e.user for e in entries})
        user_select.set_options((u, u) for u in users)
        if previous_user is not Select.BLANK and previous_user in users:
            user_select.value = previous_user

        issue_select = self.query_one("#issue-filter", Select)
        previous_issue = issue_select.value
        issues = sorted({(e.issue_id, e.issue_subject) for e in entries if e.issue_id is not None})
        issue_select.set_options(
            (f"#{issue_id}: {subject}" if subject else f"#{issue_id}", issue_id)
            for issue_id, subject in issues
        )
        issue_ids = {issue_id for issue_id, _ in issues}
        if previous_issue is not Select.BLANK and previous_issue in issue_ids:
            issue_select.value = previous_issue

        self._apply_filter()
