from pathlib import Path

from textual.screen import Screen
from textual.widgets import Footer, Header, Select

from task_log.datasource import DataSource
from task_log.day_flags import DayFlagStore
from task_log.models import TimeEntry
from task_log.ui.calendar_list_pane import CalendarListPane
from task_log.ui.edit_screen import EditEntryScreen


class TimeEntriesPane(CalendarListPane):
    """Redmine time entries, filterable by user and Redmine issue."""

    BINDINGS = [
        ("u", "focus_user_filter", "User filter"),
        ("i", "focus_issue_filter", "Issue filter"),
        ("e", "edit_entry", "Edit"),
        ("a", "add_entry", "Add"),
    ]

    COLUMNS = ("User", "Activity", "Issue", "Comment", "Hours")

    def __init__(self, datasource: DataSource, flag_store: DayFlagStore | None = None):
        super().__init__(flag_store or DayFlagStore(Path("day_flags.json")))
        self._datasource = datasource
        self._entries: list[TimeEntry] = []

    def compose_filters(self):
        yield Select([], prompt="All users", allow_blank=True, id="user-filter")
        yield Select([], prompt="All issues", allow_blank=True, id="issue-filter")

    def _row(self, e: TimeEntry) -> tuple:
        issue = f"#{e.issue_id}: {e.issue_subject}" if e.issue_id else ""
        return (e.user, e.activity, issue, e.comments, f"{e.hours:g}")

    def action_focus_user_filter(self) -> None:
        self.query_one("#user-filter", Select).focus()

    def action_focus_issue_filter(self) -> None:
        self.query_one("#issue-filter", Select).focus()

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
            EditEntryScreen(
                None,
                self._datasource,
                default_issue_id=default_issue_id,
                default_spent_on=self._calendar_day(),
            ),
            callback=self._on_edit_result,
        )

    def _on_edit_result(self, saved: bool | None) -> None:
        if saved:
            self._load_entries()

    def on_select_changed(self, event: Select.Changed) -> None:
        self._apply_filter()

    def _apply_filter(self) -> None:
        user_select = self.query_one("#user-filter", Select)
        user = None if user_select.value is Select.BLANK else user_select.value
        issue_select = self.query_one("#issue-filter", Select)
        issue_id = None if issue_select.value is Select.BLANK else issue_select.value

        self._filtered_entries = [
            e
            for e in self._entries
            if (user is None or e.user == user) and (issue_id is None or e.issue_id == issue_id)
        ]
        self._render_entries()

        labels = [user] if user is not None else []
        if issue_id is not None:
            labels.append(f"#{issue_id}")
        filtered = len(self._filtered_entries)
        if labels:
            self.sub_title = f"{' & '.join(labels)}: {filtered} of {len(self._entries)} entries"
        else:
            self.sub_title = f"{filtered} entries"

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


class TimeEntriesScreen(Screen):
    """Standalone host for TimeEntriesPane — used for isolated testing.

    The real app embeds TimeEntriesPane directly in a tab (see ui/app.py).
    """

    AUTO_FOCUS = "#entries"

    def __init__(self, datasource: DataSource, flag_store: DayFlagStore | None = None):
        super().__init__()
        self._pane = TimeEntriesPane(datasource, flag_store)

    def compose(self):
        yield Header()
        yield self._pane
        yield Footer()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        return self._pane.check_action(action, parameters)
