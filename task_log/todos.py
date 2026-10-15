"""Local, backend-independent todo tree — not a Redmine concept.

Stored as a flat JSON list of records (parent_id links form the tree),
loaded eagerly and saved on every mutation, same convention as
day_flags.py.
"""

import json
from dataclasses import dataclass, replace
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Attachment:
    name: str
    target: str  # absolute file path or URL, depending on kind
    kind: str  # "file" or "url"


@dataclass(frozen=True, slots=True)
class Todo:
    id: int
    subject: str
    description: str
    done: bool
    parent_id: int | None
    attachments: tuple[Attachment, ...] = ()
    # Redmine issue this item (and, unless overridden lower down, its whole
    # subtree) logs time against — see TodoStore.effective_redmine_issue().
    redmine_issue_id: int | None = None


class TodoNotFoundError(KeyError):
    pass


def _attachment_from_record(record: str | dict) -> Attachment:
    # todos.json files written before URL attachments existed store each
    # attachment as a plain path string — default those to kind="file" with
    # the basename as name so old files still load fine.
    if isinstance(record, str):
        return Attachment(name=Path(record).name, target=record, kind="file")
    return Attachment(name=record["name"], target=record["target"], kind=record["kind"])


class TodoStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._todos: dict[int, Todo] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        records = json.loads(self._path.read_text())
        self._todos = {
            r["id"]: Todo(
                id=r["id"],
                subject=r["subject"],
                description=r["description"],
                done=r["done"],
                parent_id=r["parent_id"],
                attachments=tuple(_attachment_from_record(a) for a in r.get("attachments", ())),
                redmine_issue_id=r.get("redmine_issue_id"),
            )
            for r in records
        }

    def _save(self) -> None:
        records = [
            {
                "id": t.id,
                "subject": t.subject,
                "description": t.description,
                "done": t.done,
                "parent_id": t.parent_id,
                "attachments": [
                    {"name": a.name, "target": a.target, "kind": a.kind} for a in t.attachments
                ],
                "redmine_issue_id": t.redmine_issue_id,
            }
            for t in self._todos.values()
        ]
        self._path.write_text(json.dumps(records, indent=2))

    def all(self) -> list[Todo]:
        return list(self._todos.values())

    def get(self, todo_id: int) -> Todo:
        try:
            return self._todos[todo_id]
        except KeyError:
            raise TodoNotFoundError(todo_id) from None

    def children_of(self, parent_id: int | None) -> list[Todo]:
        return [t for t in self._todos.values() if t.parent_id == parent_id]

    def leaves(self) -> list[Todo]:
        """Todos with no children — the only items task entries can be logged against."""
        parent_ids = {t.parent_id for t in self._todos.values() if t.parent_id is not None}
        return [t for t in self._todos.values() if t.id not in parent_ids]

    def path_label(self, todo_id: int, sep: str = " › ") -> str:
        """Subjects from the top-level ancestor down to todo_id, e.g. "Project › Feature › Leaf"."""
        subjects: list[str] = []
        current: int | None = todo_id
        while current is not None:
            todo = self.get(current)
            subjects.append(todo.subject)
            current = todo.parent_id
        return sep.join(reversed(subjects))

    def effective_redmine_issue(self, todo_id: int) -> int | None:
        """The Redmine issue of todo_id itself, else of its nearest ancestor that has one."""
        current: int | None = todo_id
        while current is not None:
            todo = self._todos.get(current)
            if todo is None:
                return None
            if todo.redmine_issue_id is not None:
                return todo.redmine_issue_id
            current = todo.parent_id
        return None

    def set_redmine_issue(self, todo_id: int, issue_id: int | None) -> Todo:
        existing = self.get(todo_id)
        updated = replace(existing, redmine_issue_id=issue_id)
        self._todos[todo_id] = updated
        self._save()
        return updated

    def add(self, *, subject: str, description: str, parent_id: int | None) -> Todo:
        new_id = max(self._todos, default=0) + 1
        todo = Todo(
            id=new_id,
            subject=subject,
            description=description,
            done=False,
            parent_id=parent_id,
        )
        self._todos[new_id] = todo
        self._save()
        return todo

    def update(self, todo_id: int, *, subject: str, description: str) -> Todo:
        existing = self.get(todo_id)
        updated = replace(existing, subject=subject, description=description)
        self._todos[todo_id] = updated
        self._save()
        return updated

    def add_attachment(self, todo_id: int, attachment: Attachment) -> Todo:
        existing = self.get(todo_id)
        if any(a.target == attachment.target for a in existing.attachments):
            return existing
        updated = replace(existing, attachments=existing.attachments + (attachment,))
        self._todos[todo_id] = updated
        self._save()
        return updated

    def remove_attachment(self, todo_id: int, target: str) -> Todo:
        existing = self.get(todo_id)
        updated = replace(
            existing, attachments=tuple(a for a in existing.attachments if a.target != target)
        )
        self._todos[todo_id] = updated
        self._save()
        return updated

    def delete(self, todo_id: int) -> None:
        to_delete = [todo_id]
        for existing_id in to_delete:
            to_delete.extend(child.id for child in self.children_of(existing_id))
        for existing_id in to_delete:
            self._todos.pop(existing_id, None)
        self._save()

    def _move_before(self, todo_id: int, before_id: int) -> None:
        # Sibling order (what children_of() exposes) is exactly the relative order
        # of same-parent_id entries in this flat dict — cross-group interleaving
        # doesn't matter, only relative position within a shared parent_id does.
        # So repositioning one entry in the whole flat order is enough to reorder
        # it within its own sibling group, without needing a separate "order" field.
        items = [(k, v) for k, v in self._todos.items() if k != todo_id]
        entry = (todo_id, self._todos[todo_id])
        index = next(i for i, (k, _) in enumerate(items) if k == before_id)
        items.insert(index, entry)
        self._todos = dict(items)

    def _move_after(self, todo_id: int, after_id: int) -> None:
        items = [(k, v) for k, v in self._todos.items() if k != todo_id]
        entry = (todo_id, self._todos[todo_id])
        index = next(i for i, (k, _) in enumerate(items) if k == after_id)
        items.insert(index + 1, entry)
        self._todos = dict(items)

    def move_up(self, todo_id: int) -> Todo | None:
        """Swap with the previous sibling. No-op (returns None) if already first."""
        todo = self.get(todo_id)
        siblings = self.children_of(todo.parent_id)
        index = siblings.index(todo)
        if index == 0:
            return None
        self._move_before(todo_id, siblings[index - 1].id)
        self._save()
        return todo

    def move_down(self, todo_id: int) -> Todo | None:
        """Swap with the next sibling. No-op (returns None) if already last."""
        todo = self.get(todo_id)
        siblings = self.children_of(todo.parent_id)
        index = siblings.index(todo)
        if index == len(siblings) - 1:
            return None
        self._move_after(todo_id, siblings[index + 1].id)
        self._save()
        return todo

    def indent(self, todo_id: int) -> Todo | None:
        """Nest one level deeper: becomes the last child of its previous sibling.

        No-op (returns None) if there's no previous sibling to become the new parent.
        """
        todo = self.get(todo_id)
        siblings = self.children_of(todo.parent_id)
        index = siblings.index(todo)
        if index == 0:
            return None
        new_parent = siblings[index - 1]
        updated = replace(todo, parent_id=new_parent.id)
        self._todos[todo_id] = updated
        existing_children = [c for c in self.children_of(new_parent.id) if c.id != todo_id]
        if existing_children:
            self._move_after(todo_id, existing_children[-1].id)
        else:
            self._move_after(todo_id, new_parent.id)
        self._save()
        return updated

    def outdent(self, todo_id: int) -> Todo | None:
        """Move up one level: becomes a sibling of its current parent, right after it.

        No-op (returns None) if todo_id is already top-level.
        """
        todo = self.get(todo_id)
        if todo.parent_id is None:
            return None
        old_parent = self.get(todo.parent_id)
        updated = replace(todo, parent_id=old_parent.parent_id)
        self._todos[todo_id] = updated
        self._move_after(todo_id, old_parent.id)
        self._save()
        return updated
