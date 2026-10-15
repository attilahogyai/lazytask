"""Task time entries — hours logged against a leaf todo item (task_log/todos.py).

Stored locally, same JSON-file-per-store convention as day_flags.py/todos.py:
flat dict keyed by id, loaded eagerly, saved on every mutation. When the todo
(or an ancestor) has a Redmine issue attached, the entry is also mirrored to a
Redmine time entry whose id is kept in redmine_entry_id — the store itself
never talks to Redmine, that's done by TaskEntryEditScreen/TaskEntriesPane.
"""

import json
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

# The one synthetic activity option (not a real Redmine activity/id), offered
# alongside the datasource's own list_activities() in TaskEntryEditScreen's
# Select — see edit_screen.py. Syncs to Redmine as edit_screen.DEFAULT_ACTIVITY.
GENERAL_ACTIVITY = "General"


@dataclass(frozen=True, slots=True)
class TaskEntry:
    id: int
    todo_id: int
    spent_on: date
    hours: float
    activity: str
    comments: str
    redmine_entry_id: int | None = None


class TaskEntryNotFoundError(KeyError):
    pass


class TaskEntryStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._entries: dict[int, TaskEntry] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        records = json.loads(self._path.read_text())
        self._entries = {
            r["id"]: TaskEntry(
                id=r["id"],
                todo_id=r["todo_id"],
                spent_on=date.fromisoformat(r["spent_on"]),
                hours=r["hours"],
                # task_entries.json files written before activity existed default to
                # GENERAL_ACTIVITY so they still load fine.
                activity=r.get("activity", GENERAL_ACTIVITY),
                comments=r.get("comments", ""),
                redmine_entry_id=r.get("redmine_entry_id"),
            )
            for r in records
        }

    def _save(self) -> None:
        records = [
            {
                "id": e.id,
                "todo_id": e.todo_id,
                "spent_on": e.spent_on.isoformat(),
                "hours": e.hours,
                "activity": e.activity,
                "comments": e.comments,
                "redmine_entry_id": e.redmine_entry_id,
            }
            for e in self._entries.values()
        ]
        self._path.write_text(json.dumps(records, indent=2))

    def all(self) -> list[TaskEntry]:
        return list(self._entries.values())

    def get(self, entry_id: int) -> TaskEntry:
        try:
            return self._entries[entry_id]
        except KeyError:
            raise TaskEntryNotFoundError(entry_id) from None

    def add(
        self,
        *,
        todo_id: int,
        spent_on: date,
        hours: float,
        activity: str,
        comments: str,
        redmine_entry_id: int | None = None,
    ) -> TaskEntry:
        new_id = max(self._entries, default=0) + 1
        entry = TaskEntry(
            id=new_id,
            todo_id=todo_id,
            spent_on=spent_on,
            hours=hours,
            activity=activity,
            comments=comments,
            redmine_entry_id=redmine_entry_id,
        )
        self._entries[new_id] = entry
        self._save()
        return entry

    def update(
        self,
        entry_id: int,
        *,
        todo_id: int,
        spent_on: date,
        hours: float,
        activity: str,
        comments: str,
        redmine_entry_id: int | None,
    ) -> TaskEntry:
        existing = self.get(entry_id)
        updated = replace(
            existing,
            todo_id=todo_id,
            spent_on=spent_on,
            hours=hours,
            activity=activity,
            comments=comments,
            redmine_entry_id=redmine_entry_id,
        )
        self._entries[entry_id] = updated
        self._save()
        return updated

    def delete(self, entry_id: int) -> None:
        self._entries.pop(entry_id, None)
        self._save()
