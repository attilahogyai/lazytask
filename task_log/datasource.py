from typing import Protocol

from task_log.models import TimeEntry


class DataSource(Protocol):
    def list_time_entries(self) -> list[TimeEntry]: ...
