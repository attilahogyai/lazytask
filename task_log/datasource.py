from datetime import date
from typing import Protocol

from task_log.models import Activity, Project, TimeEntry


class DataSource(Protocol):
    def list_time_entries(self) -> list[TimeEntry]: ...

    def list_activities(self) -> list[Activity]: ...

    def list_projects(self) -> list[Project]: ...

    def current_user_id(self) -> int: ...

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
    ) -> None: ...

    def create_time_entry(
        self,
        *,
        project_id: int,
        spent_on: date,
        hours: float,
        issue_id: int | None,
        activity_id: int,
        comments: str,
    ) -> None: ...
