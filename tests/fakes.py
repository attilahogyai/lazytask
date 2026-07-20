"""In-memory DataSource implementation for tests — no network, no config.toml."""

from datetime import date

from task_log.models import Activity, Project, TimeEntry


class FakeDataSource:
    def __init__(
        self,
        entries: list[TimeEntry] | None = None,
        activities: list[Activity] | None = None,
        projects: list[Project] | None = None,
        user_id: int = 1,
    ) -> None:
        self.entries = entries if entries is not None else []
        self.activities = activities if activities is not None else [
            Activity(id=1, name="Development", is_default=True)
        ]
        self.projects = projects if projects is not None else [Project(id=90, name="Brickz")]
        self.user_id = user_id
        self.created: list[dict] = []
        self.updated: list[dict] = []

    def list_time_entries(self) -> list[TimeEntry]:
        return list(self.entries)

    def list_activities(self) -> list[Activity]:
        return list(self.activities)

    def list_projects(self) -> list[Project]:
        return list(self.projects)

    def current_user_id(self) -> int:
        return self.user_id

    def update_time_entry(
        self,
        entry_id: int,
        *,
        project_id: int,
        spent_on: date,
        hours: float,
        issue_id: int | None,
        activity_id: int,
        comments: str,
    ) -> None:
        self.updated.append(
            dict(
                entry_id=entry_id,
                project_id=project_id,
                spent_on=spent_on,
                hours=hours,
                issue_id=issue_id,
                activity_id=activity_id,
                comments=comments,
            )
        )

    def create_time_entry(
        self,
        *,
        project_id: int,
        spent_on: date,
        hours: float,
        issue_id: int | None,
        activity_id: int,
        comments: str,
    ) -> None:
        self.created.append(
            dict(
                project_id=project_id,
                spent_on=spent_on,
                hours=hours,
                issue_id=issue_id,
                activity_id=activity_id,
                comments=comments,
            )
        )
