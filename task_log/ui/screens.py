from datetime import date

from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import ContentSwitcher, DataTable, Footer, Header, Select

from task_log.datasource import DataSource
from task_log.ui.calendar_view import MonthCalendar


class TimeEntriesScreen(Screen):
    AUTO_FOCUS = "#entries"

    CSS = """
    #user-filter {
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
        yield Select([], prompt="All users", allow_blank=True, id="user-filter")
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

    def action_prev_month(self) -> None:
        self.query_one(MonthCalendar).move_month(-1)

    def action_next_month(self) -> None:
        self.query_one(MonthCalendar).move_month(1)

    def action_this_month(self) -> None:
        self.query_one(MonthCalendar).goto_today()

    def action_refresh_entries(self) -> None:
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
        select = self.query_one("#user-filter", Select)
        user = None if select.value is Select.BLANK else select.value
        filtered = [e for e in self._entries if user is None or e.user == user]
        self._filtered_entries = filtered

        table = self.query_one("#entries", DataTable)
        table.clear()
        for e in filtered:
            issue = f"#{e.issue_id}: {e.issue_subject}" if e.issue_id else ""
            table.add_row(e.spent_on.isoformat(), e.user, e.activity, issue, e.comments, f"{e.hours:g}")
        self.query_one(MonthCalendar).set_entries(filtered)

        if user is None:
            self.sub_title = f"{len(filtered)} entries"
        else:
            self.sub_title = f"{user}: {len(filtered)} of {len(self._entries)} entries"

    def _load_entries(self) -> None:
        try:
            entries = self._datasource.list_time_entries()
        except Exception as exc:
            self.notify(f"Failed to load entries: {exc}", severity="error")
            return
        self._entries = entries

        select = self.query_one("#user-filter", Select)
        previous = select.value
        users = sorted({e.user for e in entries})
        select.set_options((u, u) for u in users)
        if previous is not Select.BLANK and previous in users:
            select.value = previous

        self._apply_filter()
