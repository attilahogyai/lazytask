from datetime import date

from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Select, Static

from task_log.datasource import DataSource
from task_log.models import TimeEntry


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
            default_activity = next((a for a in activities if a.is_default), activities[0])
            activity_value = default_activity.id
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
