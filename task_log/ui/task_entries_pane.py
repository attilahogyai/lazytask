from pathlib import Path

from textual.screen import Screen
from textual.widgets import Footer, Header, Select

from task_log.datasource import DataSource
from task_log.day_flags import DayFlagStore
from task_log.task_entries import TaskEntry, TaskEntryStore
from task_log.todos import TodoNotFoundError, TodoStore
from task_log.ui.calendar_list_pane import CalendarListPane
from task_log.ui.edit_screen import TaskEntryEditScreen, push_task_entry_to_redmine
from task_log.ui.todo_pane import ConfirmScreen


class TaskEntriesPane(CalendarListPane):
    """Task entries (hours logged against todo leaves), filterable by task and Redmine issue.

    The Issue column / filter use the todo's *effective* Redmine issue (its own,
    else the nearest ancestor's — TodoStore.effective_redmine_issue), and the
    Redmine column shows the linked Redmine time entry id, if the entry was
    mirrored there (see TaskEntryEditScreen).
    """

    BINDINGS = [
        ("s", "focus_task_filter", "Task filter"),
        ("i", "focus_issue_filter", "Issue filter"),
        ("e", "edit_entry", "Edit"),
        ("a", "add_entry", "Add"),
        ("d", "delete_entry", "Delete"),
        ("r", "sync_entry", "Sync to Redmine"),
    ]

    COLUMNS = ("User", "Activity", "Task", "Issue", "Comment", "Hours", "Redmine")

    def __init__(
        self,
        datasource: DataSource,
        todo_store: TodoStore,
        task_store: TaskEntryStore,
        flag_store: DayFlagStore | None = None,
        owner_id: str | None = None,
        owner_name: str | None = None,
    ):
        super().__init__(flag_store or DayFlagStore(Path("day_flags.json")))
        self._datasource = datasource
        self._todo_store = todo_store
        self._task_store = task_store
        self._entries: list[TaskEntry] = []
        # The configured [general] user_id/user_name (task_log/config.py) — fills
        # the User column, since every task entry is your own.
        self._owner_label = owner_name or owner_id or ""

    def compose_filters(self):
        yield Select([], prompt="All tasks", allow_blank=True, id="task-filter")
        yield Select([], prompt="All issues", allow_blank=True, id="issue-filter")

    def _todo_subject(self, todo_id: int) -> str:
        try:
            return self._todo_store.path_label(todo_id)
        except TodoNotFoundError:
            return "(deleted item)"

    def _row(self, e: TaskEntry) -> tuple:
        issue_id = self._todo_store.effective_redmine_issue(e.todo_id)
        return (
            self._owner_label,
            e.activity,
            self._todo_subject(e.todo_id),
            f"#{issue_id}" if issue_id is not None else "",
            e.comments,
            f"{e.hours:g}",
            f"#{e.redmine_entry_id}" if e.redmine_entry_id is not None else "",
        )

    def action_focus_task_filter(self) -> None:
        self.query_one("#task-filter", Select).focus()

    def action_focus_issue_filter(self) -> None:
        self.query_one("#issue-filter", Select).focus()

    def _todo_options(self, entry: TaskEntry | None = None):
        leaves = self._todo_store.leaves()
        if entry is not None and entry.todo_id not in {t.id for t in leaves}:
            # The entry's own todo may have since gained children (no longer a
            # leaf) — keep it selectable so the Select has a valid value.
            try:
                leaves = [self._todo_store.get(entry.todo_id), *leaves]
            except TodoNotFoundError:
                pass
        return leaves

    def action_add_entry(self) -> None:
        leaves = self._todo_options()
        if not leaves:
            self.notify("No task items to log against — add a leaf item in Todos first", severity="warning")
            return
        self.app.push_screen(
            TaskEntryEditScreen(
                None,
                self._task_store,
                self._todo_store,
                self._datasource,
                leaves,
                default_spent_on=self._calendar_day(),
            ),
            callback=self._on_edit_result,
        )

    def action_edit_entry(self) -> None:
        entry = self._entry_under_cursor()
        if entry is None:
            return
        self.app.push_screen(
            TaskEntryEditScreen(
                entry, self._task_store, self._todo_store, self._datasource, self._todo_options(entry)
            ),
            callback=self._on_edit_result,
        )

    def action_delete_entry(self) -> None:
        entry = self._entry_under_cursor()
        if entry is None:
            return
        if entry.redmine_entry_id is None:
            self._task_store.delete(entry.id)
            self._load_entries()
            return
        self.app.push_screen(
            ConfirmScreen(
                f"Delete this task entry and its Redmine time entry #{entry.redmine_entry_id}?"
            ),
            callback=lambda confirmed: self._on_delete_confirmed(confirmed, entry),
        )

    def action_sync_entry(self) -> None:
        """Push the entry under the cursor to Redmine as a time entry on its todo's
        effective issue — creates one if unlinked, else updates the linked one."""
        entry = self._entry_under_cursor()
        if entry is None:
            return
        issue_id = self._todo_store.effective_redmine_issue(entry.todo_id)
        if issue_id is None:
            self.notify("This task has no Redmine issue — set one in Todos ('i')", severity="warning")
            return
        try:
            redmine_entry_id = push_task_entry_to_redmine(
                self._datasource,
                redmine_entry_id=entry.redmine_entry_id,
                issue_id=issue_id,
                spent_on=entry.spent_on,
                hours=entry.hours,
                activity=entry.activity,
                comments=entry.comments,
            )
        except Exception as exc:
            self.notify(f"Failed to sync to Redmine (issue #{issue_id}): {exc}", severity="error")
            return
        verb = "Created" if entry.redmine_entry_id is None else "Updated"
        self._task_store.update(
            entry.id,
            todo_id=entry.todo_id,
            spent_on=entry.spent_on,
            hours=entry.hours,
            activity=entry.activity,
            comments=entry.comments,
            redmine_entry_id=redmine_entry_id,
        )
        self._load_entries()
        self.notify(f"{verb} Redmine time entry #{redmine_entry_id} on issue #{issue_id}")

    def _on_delete_confirmed(self, confirmed: bool | None, entry: TaskEntry) -> None:
        if not confirmed:
            return
        try:
            self._datasource.delete_time_entry(entry.redmine_entry_id)
        except Exception as exc:
            self.notify(f"Failed to delete Redmine entry: {exc}", severity="error")
            return
        self._task_store.delete(entry.id)
        self._load_entries()

    def _on_edit_result(self, saved: bool | None) -> None:
        if saved:
            self._load_entries()

    def on_select_changed(self, event: Select.Changed) -> None:
        self._apply_filter()

    def _apply_filter(self) -> None:
        task_select = self.query_one("#task-filter", Select)
        todo_id = None if task_select.value is Select.BLANK else task_select.value
        issue_select = self.query_one("#issue-filter", Select)
        issue_id = None if issue_select.value is Select.BLANK else issue_select.value

        self._filtered_entries = [
            e
            for e in self._entries
            if (todo_id is None or e.todo_id == todo_id)
            and (issue_id is None or self._todo_store.effective_redmine_issue(e.todo_id) == issue_id)
        ]
        self._render_entries()

        filtered = len(self._filtered_entries)
        if todo_id is not None or issue_id is not None:
            self.sub_title = f"{filtered} of {len(self._entries)} task entries"
        else:
            self.sub_title = f"{filtered} task entries"

    def _load_entries(self) -> None:
        # Newest first, same order Redmine returns time entries in.
        self._entries = sorted(self._task_store.all(), key=lambda e: e.spent_on, reverse=True)

        task_select = self.query_one("#task-filter", Select)
        previous_task = task_select.value
        todo_ids = sorted({e.todo_id for e in self._entries}, key=self._todo_subject)
        task_select.set_options((self._todo_subject(t), t) for t in todo_ids)
        if previous_task is not Select.BLANK and previous_task in todo_ids:
            task_select.value = previous_task

        issue_select = self.query_one("#issue-filter", Select)
        previous_issue = issue_select.value
        issue_ids = sorted(
            {
                issue_id
                for e in self._entries
                if (issue_id := self._todo_store.effective_redmine_issue(e.todo_id)) is not None
            }
        )
        issue_select.set_options((f"#{i}", i) for i in issue_ids)
        if previous_issue is not Select.BLANK and previous_issue in issue_ids:
            issue_select.value = previous_issue

        self._apply_filter()


class TaskEntriesScreen(Screen):
    """Standalone host for TaskEntriesPane — used for isolated testing.

    The real app embeds TaskEntriesPane directly in a tab (see ui/app.py).
    """

    AUTO_FOCUS = "#entries"

    def __init__(
        self,
        datasource: DataSource,
        todo_store: TodoStore,
        task_store: TaskEntryStore,
        flag_store: DayFlagStore | None = None,
        owner_id: str | None = None,
        owner_name: str | None = None,
    ):
        super().__init__()
        self._pane = TaskEntriesPane(
            datasource, todo_store, task_store, flag_store, owner_id=owner_id, owner_name=owner_name
        )

    def compose(self):
        yield Header()
        yield self._pane
        yield Footer()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        return self._pane.check_action(action, parameters)
