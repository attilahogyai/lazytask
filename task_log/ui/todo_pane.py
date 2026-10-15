import os
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import pathspec
from rich.text import Text
from textual import events
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Footer, Header, Input, OptionList, Static, TextArea, Tree
from textual.widgets.option_list import Option
from textual.widgets.tree import TreeNode

from task_log.todos import Attachment, Todo, TodoStore

_SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules", ".pytest_cache"}
_MAX_SCAN_RESULTS = 5000
_MAX_DISPLAYED_RESULTS = 300
_CD_PREFIX = "/cd"


def _load_gitignore(dir_path: Path) -> pathspec.GitIgnoreSpec | None:
    gitignore_file = dir_path / ".gitignore"
    if not gitignore_file.is_file():
        return None
    try:
        lines = gitignore_file.read_text().splitlines()
    except OSError:
        return None
    return pathspec.GitIgnoreSpec.from_lines(lines)


def _label(todo: Todo) -> Text:
    label = Text(todo.subject)
    if todo.redmine_issue_id is not None:
        label.append(f"  #{todo.redmine_issue_id}", style="cyan")
    return label


def _attachment_label(attachment: Attachment) -> str:
    return f"{attachment.name} — {attachment.target}"


def _looks_like_url(value: str) -> bool:
    return value.startswith(("http://", "https://"))


def _default_attachment_name(target: str, kind: str) -> str:
    if kind == "url":
        return urlparse(target).netloc or target
    return Path(target).name


class ConfirmScreen(ModalScreen[bool]):
    """Small reusable Yes/No confirmation modal."""

    DEFAULT_CSS = """
    ConfirmScreen {
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

    def __init__(self, message: str) -> None:
        super().__init__()
        self._message = message

    def compose(self):
        with Vertical(id="dialog"):
            yield Static(self._message)
            with Horizontal():
                yield Button("Cancel", id="cancel")
                yield Button("Delete", id="confirm", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")

    def action_cancel(self) -> None:
        self.dismiss(False)


class TodoEditScreen(ModalScreen[Todo | None]):
    """Edits an existing todo, or creates a new one (under parent_id) if todo is None."""

    DEFAULT_CSS = """
    TodoEditScreen {
        align: center middle;
    }
    #dialog {
        width: 90%;
        height: 90%;
        border: round $accent;
        padding: 1 2;
        background: $surface;
    }
    #description {
        height: 1fr;
        margin-top: 1;
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

    def __init__(self, todo: Todo | None, store: TodoStore, parent_id: int | None = None) -> None:
        super().__init__()
        self._todo = todo
        self._store = store
        self._parent_id = parent_id

    def compose(self):
        todo = self._todo
        title = f"Edit item — {todo.subject}" if todo is not None else "New item"
        subject_value = todo.subject if todo is not None else ""
        description_value = todo.description if todo is not None else ""

        with Vertical(id="dialog"):
            yield Static(title)
            yield Input(value=subject_value, placeholder="Subject", id="subject")
            yield TextArea(description_value, id="description")
            with Horizontal():
                yield Button("Cancel", id="cancel")
                yield Button("Save", id="save", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "save":
            self._save()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _save(self) -> None:
        subject = self.query_one("#subject", Input).value.strip()
        if not subject:
            self.notify("Subject is required", severity="error")
            return
        description = self.query_one("#description", TextArea).text

        if self._todo is None:
            todo = self._store.add(subject=subject, description=description, parent_id=self._parent_id)
        else:
            todo = self._store.update(self._todo.id, subject=subject, description=description)

        self.dismiss(todo)


class RedmineIssueScreen(ModalScreen[Todo | None]):
    """Attaches a Redmine issue id to a todo (blank clears it); dismisses with the updated Todo."""

    DEFAULT_CSS = """
    RedmineIssueScreen {
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

    def __init__(self, todo: Todo, store: TodoStore) -> None:
        super().__init__()
        self._todo = todo
        self._store = store

    def compose(self):
        value = str(self._todo.redmine_issue_id) if self._todo.redmine_issue_id is not None else ""
        with Vertical(id="dialog"):
            yield Static(f"Redmine issue for '{self._todo.subject}' (blank = none / inherit)")
            yield Input(value=value, placeholder="Issue #", id="issue_id")
            with Horizontal():
                yield Button("Cancel", id="cancel")
                yield Button("Save", id="save", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "save":
            self._save()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._save()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _save(self) -> None:
        raw = self.query_one("#issue_id", Input).value.strip().lstrip("#")
        if raw:
            try:
                issue_id = int(raw)
            except ValueError:
                self.notify("Issue # must be a number", severity="error")
                return
        else:
            issue_id = None
        self.dismiss(self._store.set_redmine_issue(self._todo.id, issue_id))


class FilePickerScreen(ModalScreen[Attachment | None]):
    """Filterable, recursive file/dir browser rooted at cwd — type to narrow the list.

    Also doubles as the URL-attachment form: typing (or pasting) an http(s) URL into
    the search box instead of a filter string and confirming it (Enter or Select)
    creates a "url"-kind Attachment instead of browsing/picking a file — no separate
    screen, since the two flows share the same "target + optional name" shape. The
    "#attach-name" field applies to either kind; left blank, the name defaults to the
    file's basename or the URL's host (see _default_attachment_name).
    """

    AUTO_FOCUS = "#search"

    DEFAULT_CSS = """
    FilePickerScreen {
        align: center middle;
    }
    #dialog {
        width: 90;
        height: 32;
        border: round $accent;
        padding: 1 2;
        background: $surface;
    }
    #attach-name {
        margin-bottom: 1;
    }
    #search {
        margin-bottom: 1;
    }
    #results {
        height: 1fr;
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

    def __init__(self, root: Path | None = None) -> None:
        super().__init__()
        self._root = root or Path.cwd()
        self._cwd = self._root
        self._paths = self._scan(self._cwd)

    def _scan(self, root: Path) -> list[str]:
        paths: list[str] = []
        # dir -> its own .gitignore spec (patterns relative to that dir), or None.
        # A path is ignored if ANY ancestor dir's spec (root-most first) matches it —
        # each .gitignore only covers its own subtree, same as git itself. Cross-file
        # negation (a child .gitignore un-ignoring something an ancestor ignored) isn't
        # handled — a rare enough case to skip for a personal-use file picker.
        specs: dict[Path, pathspec.GitIgnoreSpec | None] = {root: _load_gitignore(root)}

        def is_ignored(path: Path, is_dir: bool) -> bool:
            # ancestor dirs from root down to path's immediate parent, root-most first
            rel_parents = list(path.relative_to(root).parents)[:-1]  # drop the trailing '.'
            ancestors = (root, *(root / p for p in reversed(rel_parents)))
            for ancestor in ancestors:
                spec = specs.get(ancestor)
                if spec is None:
                    continue
                rel = str(path.relative_to(ancestor))
                if spec.match_file(rel + "/" if is_dir else rel):
                    return True
            return False

        for dirpath, dirnames, filenames in os.walk(root):
            current = Path(dirpath)
            dirnames[:] = [
                d for d in dirnames if d not in _SKIP_DIRS and not is_ignored(current / d, True)
            ]
            for d in dirnames:
                specs[current / d] = _load_gitignore(current / d)
            names = dirnames + [f for f in filenames if not is_ignored(current / f, False)]
            for name in names:
                paths.append(str(current / name))
                if len(paths) >= _MAX_SCAN_RESULTS:
                    return sorted(paths)
        return sorted(paths)

    def compose(self):
        with Vertical(id="dialog"):
            yield Static(f"Attach a file or URL — browsing {self._cwd}", id="picker-title")
            yield Input(placeholder="Name (optional)", id="attach-name")
            yield Input(
                placeholder="Type to filter files, paste a URL, or /cd <dir>…", id="search"
            )
            yield OptionList(id="results")
            with Horizontal():
                yield Button("Cancel", id="cancel")
                yield Button("Select", id="select", variant="primary")

    def on_mount(self) -> None:
        self._refresh_results("")

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "search" or event.value.startswith(_CD_PREFIX):
            return
        self._refresh_results(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search" and event.value.startswith(_CD_PREFIX):
            self._cd(event.value[len(_CD_PREFIX) :].strip())
            return
        self._confirm()

    def _cd(self, target: str) -> None:
        if not target:
            self.notify(f"Usage: {_CD_PREFIX} <directory>", severity="warning")
            return
        candidate = (self._cwd / target).resolve()
        root = self._root.resolve()
        if candidate != root and root not in candidate.parents:
            self.notify(f"Can't browse outside {self._root}", severity="error")
            return
        if not candidate.is_dir():
            self.notify(f"Not a directory: {target}", severity="error")
            return

        self._cwd = candidate
        self._paths = self._scan(self._cwd)
        self.query_one("#picker-title", Static).update(
            f"Attach a file or URL — browsing {self._cwd}"
        )
        search = self.query_one("#search", Input)
        search.value = ""
        self._refresh_results("")

    def on_key(self, event: events.Key) -> None:
        if event.key not in ("up", "down") or self.focused is not self.query_one("#search", Input):
            return
        results = self.query_one("#results", OptionList)
        if event.key == "down":
            results.action_cursor_down()
        else:
            results.action_cursor_up()
        event.stop()

    def _refresh_results(self, query: str) -> None:
        results = self.query_one("#results", OptionList)
        results.clear_options()
        query_lower = query.lower()
        all_matches = [p for p in self._paths if query_lower in p.lower()]
        matches = all_matches[:_MAX_DISPLAYED_RESULTS]
        results.add_options(Option(p, id=p) for p in matches)
        if matches:
            results.highlighted = 0
        if len(all_matches) > len(matches):
            results.border_title = (
                f"Showing {len(matches)} of {len(all_matches)} — "
                f"narrow with {_CD_PREFIX} <dir> or keep typing"
            )
        else:
            results.border_title = f"{len(matches)} match(es)"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "select":
            self._confirm()

    def _confirm(self) -> None:
        search_value = self.query_one("#search", Input).value
        if _looks_like_url(search_value):
            self._finalize(target=search_value.strip(), kind="url")
        else:
            self._confirm_selection()

    def _confirm_selection(self) -> None:
        results = self.query_one("#results", OptionList)
        if results.highlighted is None:
            self.notify("No file selected", severity="error")
            return
        option = results.get_option_at_index(results.highlighted)
        self._finalize(target=option.id, kind="file")

    def _finalize(self, *, target: str, kind: str) -> None:
        name = self.query_one("#attach-name", Input).value.strip()
        name = name or _default_attachment_name(target, kind)
        self.dismiss(Attachment(name=name, target=target, kind=kind))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self._finalize(target=event.option.id, kind="file")

    def action_cancel(self) -> None:
        self.dismiss(None)


class AttachmentPickerScreen(ModalScreen[str | None]):
    """Pick one of a todo's existing attachments (used by detach/open when there's more than one)."""

    DEFAULT_CSS = """
    AttachmentPickerScreen {
        align: center middle;
    }
    #dialog {
        width: 80;
        height: auto;
        max-height: 20;
        border: round $accent;
        padding: 1 2;
        background: $surface;
    }
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, title: str, attachments: tuple[Attachment, ...]) -> None:
        super().__init__()
        self._title = title
        self._attachments = attachments

    def compose(self):
        with Vertical(id="dialog"):
            yield Static(self._title)
            yield OptionList(*(_attachment_label(a) for a in self._attachments))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(self._attachments[event.option_index].target)

    def action_cancel(self) -> None:
        self.dismiss(None)


class TodoPane(Horizontal):
    DEFAULT_CSS = """
    #todo-tree {
        height: 1fr;
    }
    #todo-detail {
        border: round $accent;
        border-title-align: center;
        height: auto;
        max-width: 40%;
        padding: 0 1;
    }
    """

    BINDINGS = [
        ("a", "add_child", "Add sub-item"),
        ("A", "add_top", "Add top-level item"),
        ("e", "edit_item", "Edit"),
        ("d", "delete_item", "Delete"),
        ("f", "attach_file", "Attach"),
        ("F", "detach_file", "Detach"),
        ("o", "open_file", "Open file"),
        ("i", "set_redmine_issue", "Redmine issue"),
        ("m", "toggle_organize_mode", "Reorder mode"),
    ]

    def __init__(self, store: TodoStore, attachments_root: Path | None = None) -> None:
        super().__init__()
        self._store = store
        self._attachments_root = attachments_root
        self._organize_mode = False

    def compose(self):
        yield Tree("Todos", id="todo-tree")
        yield Static(id="todo-detail")

    def on_mount(self) -> None:
        tree = self.query_one(Tree)
        tree.show_root = False
        tree.auto_expand = False
        self._build_children(tree.root, parent_id=None)
        self.query_one("#todo-detail", Static).border_title = "Todo details"

    def _build_children(
        self, node: TreeNode, parent_id: int | None, expanded: dict[int, bool] | None = None
    ) -> None:
        for todo in self._store.children_of(parent_id):
            should_expand = True if expanded is None else expanded.get(todo.id, True)
            child = node.add(_label(todo), data=todo.id, expand=should_expand)
            self._build_children(child, todo.id, expanded)

    def _snapshot_expanded(self) -> dict[int, bool]:
        state: dict[int, bool] = {}

        def walk(node: TreeNode) -> None:
            for child in node.children:
                if child.data is not None:
                    state[child.data] = child.is_expanded
                walk(child)

        walk(self.query_one(Tree).root)
        return state

    def _find_node(self, node: TreeNode, todo_id: int) -> TreeNode | None:
        for child in node.children:
            if child.data == todo_id:
                return child
            found = self._find_node(child, todo_id)
            if found is not None:
                return found
        return None

    def _rebuild_tree(self, select_id: int | None = None) -> None:
        tree = self.query_one(Tree)
        expanded = self._snapshot_expanded()
        tree.root.remove_children()
        self._build_children(tree.root, parent_id=None, expanded=expanded)
        if select_id is not None:
            node = self._find_node(tree.root, select_id)
            if node is not None:
                # move_cursor() reads node._line, which is only populated when the
                # tree's line cache is (re)built — force that now, since add()/
                # remove_children() above only invalidated the cache, they don't
                # rebuild it; without this, node._line is stale and the cursor
                # lands on the wrong row.
                _ = tree._tree_lines
                tree.move_cursor(node)

    def _cursor_todo_id(self) -> int | None:
        node = self.query_one(Tree).cursor_node
        return None if node is None else node.data

    def action_toggle_organize_mode(self) -> None:
        self._organize_mode = not self._organize_mode
        if self._organize_mode:
            self.notify("Reorder mode: Up/Down move, Left/Right outdent/indent, m to exit")
        else:
            self.notify("Reorder mode off")

    def on_key(self, event: events.Key) -> None:
        if not self._organize_mode:
            return
        if event.key == "m":
            event.stop()
            self._organize_mode = False
            self.notify("Reorder mode off")
        elif event.key == "up":
            event.stop()
            self._reorder(self._store.move_up)
        elif event.key == "down":
            event.stop()
            self._reorder(self._store.move_down)
        elif event.key == "right":
            event.stop()
            self._reorder(self._store.indent, none_message="No previous sibling to nest under")
        elif event.key == "left":
            event.stop()
            self._reorder(self._store.outdent, none_message="Already at the top level")
        else:
            # Any other key (including escape) cancels reorder mode and falls
            # through unstopped to its normal binding, same convention as the
            # flag-mode pattern in time_entries_pane.py.
            self._organize_mode = False

    def _reorder(self, mover, none_message: str | None = None) -> None:
        todo_id = self._cursor_todo_id()
        if todo_id is None:
            return
        result = mover(todo_id)
        if result is None:
            if none_message:
                self.notify(none_message, severity="warning")
            return
        self._rebuild_tree(select_id=todo_id)

    def action_add_child(self) -> None:
        tree = self.query_one(Tree)
        node = tree.cursor_node
        parent_id = None if node is None else node.data
        parent_node = tree.root if node is None else node
        self.app.push_screen(
            TodoEditScreen(None, self._store, parent_id=parent_id),
            callback=lambda todo: self._on_added(todo, parent_node),
        )

    def action_add_top(self) -> None:
        tree = self.query_one(Tree)
        self.app.push_screen(
            TodoEditScreen(None, self._store, parent_id=None),
            callback=lambda todo: self._on_added(todo, tree.root),
        )

    def _on_added(self, todo: Todo | None, parent_node: TreeNode) -> None:
        if todo is None:
            return
        new_node = parent_node.add(_label(todo), data=todo.id)
        parent_node.expand()
        self.query_one(Tree).move_cursor(new_node)

    def action_edit_item(self) -> None:
        todo_id = self._cursor_todo_id()
        if todo_id is None:
            return
        node = self.query_one(Tree).cursor_node
        self.app.push_screen(
            TodoEditScreen(self._store.get(todo_id), self._store),
            callback=lambda todo: self._on_edited(todo, node),
        )

    def _on_edited(self, todo: Todo | None, node: TreeNode) -> None:
        if todo is None:
            return
        node.label = _label(todo)
        self._show_detail(todo)

    def action_delete_item(self) -> None:
        todo_id = self._cursor_todo_id()
        if todo_id is None:
            return
        node = self.query_one(Tree).cursor_node
        todo = self._store.get(todo_id)
        descendants = self._count_descendants(todo_id)
        message = f"Delete '{todo.subject}'" + (
            f" and {descendants} sub-item(s)?" if descendants else "?"
        )
        self.app.push_screen(
            ConfirmScreen(message),
            callback=lambda confirmed: self._on_delete_confirmed(confirmed, todo_id, node),
        )

    def _count_descendants(self, todo_id: int) -> int:
        children = self._store.children_of(todo_id)
        return len(children) + sum(self._count_descendants(c.id) for c in children)

    def _on_delete_confirmed(self, confirmed: bool | None, todo_id: int, node: TreeNode) -> None:
        if not confirmed:
            return
        self._store.delete(todo_id)
        node.remove()

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        if event.node.data is None:
            return
        self._show_detail(self._store.get(event.node.data))

    def action_set_redmine_issue(self) -> None:
        todo_id = self._cursor_todo_id()
        if todo_id is None:
            self.notify("Select an item first", severity="warning")
            return
        node = self.query_one(Tree).cursor_node
        self.app.push_screen(
            RedmineIssueScreen(self._store.get(todo_id), self._store),
            callback=lambda todo: self._on_edited(todo, node),
        )

    def _redmine_issue_line(self, todo: Todo) -> str | None:
        if todo.redmine_issue_id is not None:
            return f"Redmine issue: #{todo.redmine_issue_id}"
        issue_id = self._store.effective_redmine_issue(todo.id)
        if issue_id is None:
            return None
        return f"Redmine issue: #{issue_id} (inherited)"

    def _show_detail(self, todo: Todo) -> None:
        lines = [todo.description or "(no description)"]
        issue_line = self._redmine_issue_line(todo)
        if issue_line:
            lines.extend(["", issue_line])
        if todo.attachments:
            lines.append("")
            lines.append("Attachments:")
            lines.extend(f"  {_attachment_label(a)}" for a in todo.attachments)
        self.query_one("#todo-detail", Static).update("\n".join(lines))

    def action_attach_file(self) -> None:
        todo_id = self._cursor_todo_id()
        if todo_id is None:
            self.notify("Select an item first", severity="warning")
            return
        self.app.push_screen(
            FilePickerScreen(root=self._attachments_root),
            callback=lambda attachment: self._on_attachment_picked(attachment, todo_id),
        )

    def _on_attachment_picked(self, attachment: Attachment | None, todo_id: int) -> None:
        if attachment is None:
            return
        todo = self._store.add_attachment(todo_id, attachment)
        self._show_detail(todo)
        self.notify(f"Attached {attachment.name}")

    def _pick_attachment(self, todo: Todo, title: str, on_picked) -> None:
        if not todo.attachments:
            self.notify("No attachments", severity="warning")
            return
        if len(todo.attachments) == 1:
            on_picked(todo.attachments[0].target)
            return
        self.app.push_screen(
            AttachmentPickerScreen(title, todo.attachments),
            callback=lambda target: on_picked(target) if target is not None else None,
        )

    def action_detach_file(self) -> None:
        todo_id = self._cursor_todo_id()
        if todo_id is None:
            return
        todo = self._store.get(todo_id)
        self._pick_attachment(
            todo, "Detach which attachment?", lambda target: self._do_detach(todo_id, target)
        )

    def _do_detach(self, todo_id: int, target: str) -> None:
        todo = self._store.remove_attachment(todo_id, target)
        self._show_detail(todo)
        self.notify(f"Detached {target}")

    def action_open_file(self) -> None:
        todo_id = self._cursor_todo_id()
        if todo_id is None:
            return
        todo = self._store.get(todo_id)
        self._pick_attachment(todo, "Open which attachment?", self._do_open)

    def _do_open(self, target: str) -> None:
        try:
            subprocess.Popen(
                ["xdg-open", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except OSError as exc:
            self.notify(f"Failed to open {target}: {exc}", severity="error")


class TodoScreen(Screen):
    """Standalone host for TodoPane — used for isolated testing."""

    AUTO_FOCUS = "#todo-tree"

    def __init__(self, store: TodoStore, attachments_root: Path | None = None) -> None:
        super().__init__()
        self._pane = TodoPane(store, attachments_root=attachments_root)

    def compose(self):
        yield Header()
        yield self._pane
        yield Footer()
