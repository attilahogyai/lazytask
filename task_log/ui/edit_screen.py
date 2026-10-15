from datetime import date

from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Select, Static

from task_log.datasource import DataSource
from task_log.models import Activity, TimeEntry
from task_log.task_entries import GENERAL_ACTIVITY, TaskEntry, TaskEntryStore
from task_log.todos import Todo, TodoStore


# Preselected activity for new entries. Redmine's own is_default flag wins if
# an admin ever sets one — this instance has none flagged.
DEFAULT_ACTIVITY = "Fejlesztés"


def default_activity(activities: list[Activity]) -> Activity:
    return (
        next((a for a in activities if a.is_default), None)
        or next((a for a in activities if a.name == DEFAULT_ACTIVITY), None)
        or activities[0]
    )


def _redmine_activity_id(datasource: DataSource, activity: str) -> int:
    # Task entries hold an activity *name*; Redmine needs an id. GENERAL_ACTIVITY
    # (or a name Redmine no longer has) maps to the default activity.
    activities = datasource.list_activities()
    match = next((a for a in activities if a.name == activity), None)
    return (match or default_activity(activities)).id


def push_task_entry_to_redmine(
    datasource: DataSource,
    *,
    redmine_entry_id: int | None,
    issue_id: int | None,
    spent_on: date,
    hours: float,
    activity: str,
    comments: str,
) -> int:
    """Create (unlinked) or update (linked) the Redmine time entry mirroring a
    task entry; returns its Redmine id. Raises whatever the datasource raises."""
    # Redmine rejects an issue from a different project than project_id
    # ("Issue is invalid"), so log under the issue's own project.
    if issue_id is not None:
        project_id = datasource.issue_project_id(issue_id)
    else:
        project_id = datasource.list_projects()[0].id
    fields = dict(
        project_id=project_id,
        spent_on=spent_on,
        hours=hours,
        issue_id=issue_id,
        activity_id=_redmine_activity_id(datasource, activity),
        comments=comments,
    )
    if redmine_entry_id is None:
        return datasource.create_time_entry(**fields)
    datasource.update_time_entry(redmine_entry_id, **fields)
    return redmine_entry_id


class EditEntryScreen(ModalScreen[bool]):
    """Edits an existing entry, or creates a new one if entry is None."""

    DEFAULT_CSS = """
    EditEntryScreen {
        align: center middle;
    }
    #dialog {
        width: 60;
        height: auto;
        border: round $accent;
        padding: 1 2;
        background: $surface;
    }
    #dialog > Horizontal {
        height: auto;
        align: right middle;
        margin-top: 1;
    }
    #dialog Button {
        margin-left: 1;
    }
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(
        self,
        entry: TimeEntry | None,
        datasource: DataSource,
        default_issue_id: int | None = None,
        default_spent_on: date | None = None,
    ):
        super().__init__()
        self._entry = entry
        self._datasource = datasource
        self._default_issue_id = default_issue_id
        self._default_spent_on = default_spent_on

    def compose(self):
        e = self._entry
        projects = self._datasource.list_projects()
        activities = self._datasource.list_activities()

        if e is None:
            title = "New time entry"
            project_value = projects[0].id
            activity_value = default_activity(activities).id
            spent_on_value = (self._default_spent_on or date.today()).isoformat()
            hours_value = ""
            issue_value = str(self._default_issue_id) if self._default_issue_id else ""
            comments_value = ""
        else:
            title = f"Edit entry #{e.id} — {e.spent_on.isoformat()}"
            project_value = e.project_id
            activity_value = e.activity_id
            spent_on_value = e.spent_on.isoformat()
            hours_value = f"{e.hours:g}"
            issue_value = str(e.issue_id) if e.issue_id else ""
            comments_value = e.comments

        with Vertical(id="dialog"):
            yield Static(title)
            yield Select(
                [(p.name, p.id) for p in projects],
                value=project_value,
                allow_blank=False,
                id="project",
            )
            yield Input(value=spent_on_value, placeholder="YYYY-MM-DD", id="spent_on")
            yield Input(value=hours_value, placeholder="Hours", id="hours")
            yield Input(value=issue_value, placeholder="Issue # (optional)", id="issue_id")
            yield Select(
                [(a.name, a.id) for a in activities],
                value=activity_value,
                allow_blank=False,
                id="activity",
            )
            yield Input(value=comments_value, placeholder="Comments", id="comments")
            with Horizontal():
                yield Button("Cancel", id="cancel")
                yield Button("Save", id="save", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(False)
        elif event.button.id == "save":
            self._save()

    def action_cancel(self) -> None:
        self.dismiss(False)

    def _save(self) -> None:
        try:
            spent_on = date.fromisoformat(self.query_one("#spent_on", Input).value.strip())
        except ValueError:
            self.notify("Date must be YYYY-MM-DD", severity="error")
            return

        try:
            hours = float(self.query_one("#hours", Input).value.strip())
        except ValueError:
            self.notify("Hours must be a number", severity="error")
            return

        issue_raw = self.query_one("#issue_id", Input).value.strip()
        if issue_raw:
            try:
                issue_id = int(issue_raw)
            except ValueError:
                self.notify("Issue # must be a number", severity="error")
                return
        else:
            issue_id = None

        comments = self.query_one("#comments", Input).value
        project_id = self.query_one("#project", Select).value
        activity_id = self.query_one("#activity", Select).value

        try:
            if self._entry is None:
                self._datasource.create_time_entry(
                    project_id=project_id,
                    spent_on=spent_on,
                    hours=hours,
                    issue_id=issue_id,
                    activity_id=activity_id,
                    comments=comments,
                )
            else:
                self._datasource.update_time_entry(
                    self._entry.id,
                    project_id=project_id,
                    spent_on=spent_on,
                    hours=hours,
                    issue_id=issue_id,
                    activity_id=activity_id,
                    comments=comments,
                )
        except Exception as exc:
            self.notify(f"Failed to save: {exc}", severity="error")
            return

        self.dismiss(True)


class TaskEntryEditScreen(ModalScreen[bool]):
    """Edits or creates a task entry — hours logged against a todo leaf.

    Same "doubles as add/edit" shape as EditEntryScreen above. `todos` is the
    option list for the todo Select — normally TodoStore.leaves(), plus the
    entry's own todo when editing one whose todo has since gained children (so
    the Select always has a valid value to preselect). The Activity Select's
    options are GENERAL_ACTIVITY plus datasource.list_activities() names.

    Redmine sync: if the chosen todo resolves to a Redmine issue
    (TodoStore.effective_redmine_issue — its own, else the nearest ancestor's),
    Save first creates (or, if the entry is already linked, updates) a Redmine
    time entry on that issue, then stores the returned id in the task entry's
    redmine_entry_id. An already-linked entry whose todo no longer resolves to
    an issue is still updated in Redmine, with its issue cleared. A Redmine
    failure keeps the form open and saves nothing locally, so the two never
    drift apart.
    """

    DEFAULT_CSS = """
    TaskEntryEditScreen {
        align: center middle;
    }
    #dialog {
        width: 60;
        height: auto;
        border: round $accent;
        padding: 1 2;
        background: $surface;
    }
    #redmine-target {
        color: $text-muted;
    }
    #dialog > Horizontal {
        height: auto;
        align: right middle;
        margin-top: 1;
    }
    #dialog Button {
        margin-left: 1;
    }
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(
        self,
        entry: TaskEntry | None,
        store: TaskEntryStore,
        todo_store: TodoStore,
        datasource: DataSource,
        todos: list[Todo],
        default_spent_on: date | None = None,
    ):
        super().__init__()
        self._entry = entry
        self._store = store
        self._todo_store = todo_store
        self._datasource = datasource
        self._todos = todos
        self._default_spent_on = default_spent_on

    def _activity_options(self) -> list[str]:
        names = [GENERAL_ACTIVITY, *(a.name for a in self._datasource.list_activities())]
        if self._entry is not None and self._entry.activity not in names:
            names.append(self._entry.activity)
        return names

    def compose(self):
        e = self._entry
        activities = self._activity_options()
        if e is None:
            title = "New task entry"
            todo_value = self._todos[0].id
            spent_on_value = (self._default_spent_on or date.today()).isoformat()
            hours_value = ""
            activity_value = default_activity(self._datasource.list_activities()).name
            comments_value = ""
        else:
            title = f"Edit task entry #{e.id} — {e.spent_on.isoformat()}"
            todo_value = e.todo_id
            spent_on_value = e.spent_on.isoformat()
            hours_value = f"{e.hours:g}"
            activity_value = e.activity
            comments_value = e.comments

        with Vertical(id="dialog"):
            yield Static(title)
            yield Select(
                [(self._todo_store.path_label(t.id), t.id) for t in self._todos],
                value=todo_value,
                allow_blank=False,
                id="todo",
            )
            yield Static(self._redmine_target_text(todo_value), id="redmine-target")
            yield Input(value=spent_on_value, placeholder="YYYY-MM-DD", id="spent_on")
            yield Input(value=hours_value, placeholder="Hours", id="hours")
            yield Select(
                [(name, name) for name in activities],
                value=activity_value,
                allow_blank=False,
                id="activity",
            )
            yield Input(value=comments_value, placeholder="Comments (optional)", id="comments")
            with Horizontal():
                yield Button("Cancel", id="cancel")
                yield Button("Save", id="save", variant="primary")

    def _redmine_target_text(self, todo_id: int) -> str:
        issue_id = self._todo_store.effective_redmine_issue(todo_id)
        linked = self._entry.redmine_entry_id if self._entry is not None else None
        if issue_id is None:
            if linked is not None:
                return f"Redmine entry #{linked} — issue will be cleared"
            return "No Redmine issue — saved locally only"
        if linked is not None:
            return f"Redmine issue #{issue_id} — updates Redmine entry #{linked}"
        return f"Redmine issue #{issue_id} — also logged to Redmine"

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "todo" and event.value is not Select.BLANK:
            self.query_one("#redmine-target", Static).update(self._redmine_target_text(event.value))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(False)
        elif event.button.id == "save":
            self._save()

    def action_cancel(self) -> None:
        self.dismiss(False)

    def _save(self) -> None:
        try:
            spent_on = date.fromisoformat(self.query_one("#spent_on", Input).value.strip())
        except ValueError:
            self.notify("Date must be YYYY-MM-DD", severity="error")
            return

        try:
            hours = float(self.query_one("#hours", Input).value.strip())
        except ValueError:
            self.notify("Hours must be a number", severity="error")
            return

        comments = self.query_one("#comments", Input).value
        todo_id = self.query_one("#todo", Select).value
        activity = self.query_one("#activity", Select).value

        issue_id = self._todo_store.effective_redmine_issue(todo_id)
        redmine_entry_id = self._entry.redmine_entry_id if self._entry is not None else None
        if issue_id is not None or redmine_entry_id is not None:
            try:
                redmine_entry_id = push_task_entry_to_redmine(
                    self._datasource,
                    redmine_entry_id=redmine_entry_id,
                    issue_id=issue_id,
                    spent_on=spent_on,
                    hours=hours,
                    activity=activity,
                    comments=comments,
                )
            except Exception as exc:
                self.notify(f"Failed to save to Redmine: {exc}", severity="error")
                return

        if self._entry is None:
            self._store.add(
                todo_id=todo_id,
                spent_on=spent_on,
                hours=hours,
                activity=activity,
                comments=comments,
                redmine_entry_id=redmine_entry_id,
            )
        else:
            self._store.update(
                self._entry.id,
                todo_id=todo_id,
                spent_on=spent_on,
                hours=hours,
                activity=activity,
                comments=comments,
                redmine_entry_id=redmine_entry_id,
            )

        self.dismiss(True)
