from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class TimeEntry:
    id: int
    spent_on: date
    hours: float
    project: str
    issue_id: int | None
    issue_subject: str | None
    user: str
    activity: str
    comments: str
