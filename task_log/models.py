from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class Activity:
    id: int
    name: str
    is_default: bool


@dataclass(frozen=True, slots=True)
class Project:
    id: int
    name: str


@dataclass(frozen=True, slots=True)
class TimeEntry:
    id: int
    spent_on: date
    hours: float
    project: str
    project_id: int
    issue_id: int | None
    issue_subject: str | None
    user: str
    user_id: int
    activity: str
    activity_id: int
    comments: str
