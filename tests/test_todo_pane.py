"""Regression tests for the Todos tab: add/edit/delete,
expand/collapse, and file attachments, driven through TodoPane via TodoScreen
(Textual App.run_test() Pilot), against a real TodoStore backed by a tmp_path
JSON file (same no-fake-needed convention as DayFlagStore in test_day_flags.py).
"""

import json
from pathlib import Path

from textual.app import App
from textual.widgets import Input, OptionList, Static, Tree

from task_log.todos import TodoStore
from task_log.ui import todo_pane
from task_log.ui.todo_pane import ConfirmScreen, FilePickerScreen, TodoEditScreen, TodoScreen


class HarnessApp(App):
    """Pushes TodoScreen directly, skipping config/network setup."""

    def __init__(self, store: TodoStore) -> None:
        super().__init__()
        self.store = store

    def on_mount(self) -> None:
        self.push_screen(TodoScreen(self.store))


async def _add_item(pilot, key: str, subject: str) -> None:
    await pilot.press(key)
    await pilot.pause()
    screen = pilot.app.screen
    assert isinstance(screen, TodoEditScreen)
    screen.query_one("#subject", Input).value = subject
    await pilot.click("#save")
    await pilot.pause()


async def test_add_top_level_item(tmp_path):
    store = TodoStore(tmp_path / "todos.json")
    app = HarnessApp(store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _add_item(pilot, "a", "Buy milk")

        tree = app.query_one(Tree)
        assert len(tree.root.children) == 1
        assert "Buy milk" in tree.root.children[0].label.plain
        assert store.children_of(None)[0].subject == "Buy milk"


async def test_add_child_nests_under_selected_item(tmp_path):
    store = TodoStore(tmp_path / "todos.json")
    app = HarnessApp(store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _add_item(pilot, "a", "Parent")
        # cursor is left on the just-added node by _on_added
        await _add_item(pilot, "a", "Child")

        tree = app.query_one(Tree)
        assert len(tree.root.children) == 1
        parent_node = tree.root.children[0]
        assert len(parent_node.children) == 1
        assert "Child" in parent_node.children[0].label.plain

        parent = store.children_of(None)[0]
        child = store.children_of(parent.id)[0]
        assert child.subject == "Child"
        assert child.parent_id == parent.id


async def test_add_top_level_ignores_current_selection(tmp_path):
    store = TodoStore(tmp_path / "todos.json")
    app = HarnessApp(store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _add_item(pilot, "a", "Parent")
        # cursor now on "Parent"; Shift+A must still add at top level
        await _add_item(pilot, "A", "Sibling")

        tree = app.query_one(Tree)
        assert len(tree.root.children) == 2
        assert store.children_of(None)[1].parent_id is None


async def test_edit_updates_subject_in_place(tmp_path):
    store = TodoStore(tmp_path / "todos.json")
    app = HarnessApp(store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _add_item(pilot, "a", "Old subject")

        await pilot.press("e")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, TodoEditScreen)
        subject_input = screen.query_one("#subject", Input)
        assert subject_input.value == "Old subject"
        subject_input.value = "New subject"
        await pilot.click("#save")
        await pilot.pause()

        tree = app.query_one(Tree)
        assert "New subject" in tree.root.children[0].label.plain
        assert store.children_of(None)[0].subject == "New subject"


async def test_edit_preserves_attachments(tmp_path, monkeypatch):
    (tmp_path / "notes.txt").write_text("hello")
    monkeypatch.chdir(tmp_path)
    store = TodoStore(tmp_path / "todos.json")
    app = HarnessApp(store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _add_item(pilot, "a", "Task")
        await pilot.press("f")
        await pilot.pause()
        await pilot.press("n", "o", "t", "e", "s")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        todo_id = store.children_of(None)[0].id
        assert len(store.get(todo_id).attachments) == 1

        await pilot.press("e")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, TodoEditScreen)
        screen.query_one("#subject", Input).value = "Task (edited)"
        await pilot.click("#save")
        await pilot.pause()

        assert len(store.get(todo_id).attachments) == 1
        assert store.get(todo_id).subject == "Task (edited)"


async def test_enter_does_not_mark_done(tmp_path):
    store = TodoStore(tmp_path / "todos.json")
    app = HarnessApp(store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _add_item(pilot, "a", "Task")
        todo_id = store.children_of(None)[0].id

        await pilot.press("enter")
        await pilot.pause()

        assert store.get(todo_id).done is False
        label = app.query_one(Tree).root.children[0].label
        assert label.plain == "Task"
        assert "strike" not in str(label.style)


async def test_space_collapses_and_expands_children(tmp_path):
    store = TodoStore(tmp_path / "todos.json")
    app = HarnessApp(store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _add_item(pilot, "a", "Parent")
        await _add_item(pilot, "a", "Child")

        tree = app.query_one(Tree)
        parent_node = tree.root.children[0]
        await pilot.press("up")  # move cursor back onto Parent
        await pilot.pause()
        assert parent_node.is_expanded is True

        await pilot.press("space")
        await pilot.pause()
        assert parent_node.is_expanded is False

        await pilot.press("space")
        await pilot.pause()
        assert parent_node.is_expanded is True


async def test_delete_cascades_after_confirm(tmp_path):
    store = TodoStore(tmp_path / "todos.json")
    app = HarnessApp(store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _add_item(pilot, "a", "Parent")
        await _add_item(pilot, "a", "Child")

        tree = app.query_one(Tree)
        parent_node = tree.root.children[0]
        parent_id = parent_node.data
        child_id = parent_node.children[0].data

        await pilot.press("up")  # cursor back onto Parent
        await pilot.pause()
        await pilot.press("d")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmScreen)

        await pilot.click("#confirm")
        await pilot.pause()

        assert len(tree.root.children) == 0
        assert parent_id not in {t.id for t in store.all()}
        assert child_id not in {t.id for t in store.all()}


async def test_delete_cancel_keeps_item(tmp_path):
    store = TodoStore(tmp_path / "todos.json")
    app = HarnessApp(store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _add_item(pilot, "a", "Keep me")

        await pilot.press("d")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmScreen)

        await pilot.click("#cancel")
        await pilot.pause()

        tree = app.query_one(Tree)
        assert len(tree.root.children) == 1
        assert len(store.all()) == 1


async def test_attach_file_via_picker(tmp_path, monkeypatch):
    (tmp_path / "notes.txt").write_text("hello")
    monkeypatch.chdir(tmp_path)
    store = TodoStore(tmp_path / "todos.json")
    app = HarnessApp(store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _add_item(pilot, "a", "Task")

        await pilot.press("f")
        await pilot.pause()
        assert isinstance(app.screen, FilePickerScreen)
        await pilot.press("n", "o", "t", "e", "s")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        todo_id = store.children_of(None)[0].id
        todo = store.get(todo_id)
        assert len(todo.attachments) == 1
        attachment = todo.attachments[0]
        assert attachment.kind == "file"
        assert attachment.target.endswith("notes.txt")
        assert attachment.name == "notes.txt"  # default name, derived from the basename

        detail = str(app.query_one("#todo-detail", Static).renderable)
        assert "notes.txt" in detail


async def test_attach_file_with_custom_name(tmp_path, monkeypatch):
    (tmp_path / "notes.txt").write_text("hello")
    monkeypatch.chdir(tmp_path)
    store = TodoStore(tmp_path / "todos.json")
    app = HarnessApp(store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _add_item(pilot, "a", "Task")

        await pilot.press("f")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, FilePickerScreen)
        screen.query_one("#attach-name", Input).value = "My notes"
        for ch in "notes":
            await pilot.press(ch)
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        todo_id = store.children_of(None)[0].id
        attachment = store.get(todo_id).attachments[0]
        assert attachment.kind == "file"
        assert attachment.target.endswith("notes.txt")
        assert attachment.name == "My notes"


async def test_attach_url_with_default_name(tmp_path):
    store = TodoStore(tmp_path / "todos.json")
    app = HarnessApp(store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _add_item(pilot, "a", "Task")

        await pilot.press("f")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, FilePickerScreen)
        screen.query_one("#search", Input).value = "https://example.com/page"
        await pilot.press("enter")
        await pilot.pause()

        todo_id = store.children_of(None)[0].id
        attachment = store.get(todo_id).attachments[0]
        assert attachment.kind == "url"
        assert attachment.target == "https://example.com/page"
        assert attachment.name == "example.com"  # default name, derived from the URL's host

        detail = str(app.query_one("#todo-detail", Static).renderable)
        assert "example.com" in detail
        assert "https://example.com/page" in detail


async def test_attach_url_with_custom_name(tmp_path):
    store = TodoStore(tmp_path / "todos.json")
    app = HarnessApp(store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _add_item(pilot, "a", "Task")

        await pilot.press("f")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, FilePickerScreen)
        screen.query_one("#attach-name", Input).value = "Docs"
        screen.query_one("#search", Input).value = "https://example.com/docs"
        await pilot.press("enter")
        await pilot.pause()

        todo_id = store.children_of(None)[0].id
        attachment = store.get(todo_id).attachments[0]
        assert attachment.kind == "url"
        assert attachment.target == "https://example.com/docs"
        assert attachment.name == "Docs"


async def test_detach_only_attachment_removes_it_directly(tmp_path, monkeypatch):
    (tmp_path / "notes.txt").write_text("hello")
    monkeypatch.chdir(tmp_path)
    store = TodoStore(tmp_path / "todos.json")
    app = HarnessApp(store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _add_item(pilot, "a", "Task")
        await pilot.press("f")
        await pilot.pause()
        await pilot.press("n", "o", "t", "e", "s")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        todo_id = store.children_of(None)[0].id
        assert len(store.get(todo_id).attachments) == 1

        await pilot.press("F")
        await pilot.pause()

        assert store.get(todo_id).attachments == ()


async def test_open_file_shells_out_to_xdg_open(tmp_path, monkeypatch):
    (tmp_path / "notes.txt").write_text("hello")
    monkeypatch.chdir(tmp_path)
    calls = []
    monkeypatch.setattr(
        todo_pane.subprocess, "Popen", lambda args, **kwargs: calls.append(args)
    )
    store = TodoStore(tmp_path / "todos.json")
    app = HarnessApp(store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _add_item(pilot, "a", "Task")
        await pilot.press("f")
        await pilot.pause()
        await pilot.press("n", "o", "t", "e", "s")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        await pilot.press("o")
        await pilot.pause()

        assert len(calls) == 1
        assert calls[0][0] == "xdg-open"
        assert calls[0][1].endswith("notes.txt")


async def test_open_with_multiple_attachments_prompts_a_picker(tmp_path, monkeypatch):
    (tmp_path / "alpha.txt").write_text("a")
    (tmp_path / "beta.txt").write_text("b")
    monkeypatch.chdir(tmp_path)
    calls = []
    monkeypatch.setattr(
        todo_pane.subprocess, "Popen", lambda args, **kwargs: calls.append(args)
    )
    store = TodoStore(tmp_path / "todos.json")
    app = HarnessApp(store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _add_item(pilot, "a", "Task")
        todo_id = store.children_of(None)[0].id

        for name in ("alpha", "beta"):
            await pilot.press("f")
            await pilot.pause()
            for ch in name:
                await pilot.press(ch)
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

        assert len(store.get(todo_id).attachments) == 2

        await pilot.press("o")
        await pilot.pause()
        picker = app.screen
        assert isinstance(picker.query_one(OptionList), OptionList)
        await pilot.press("enter")  # confirm whichever is highlighted first
        await pilot.pause()

        assert len(calls) == 1
        assert calls[0][0] == "xdg-open"


async def test_legacy_string_attachments_load_as_file_kind(tmp_path):
    """todos.json files written before URL attachments existed store each attachment
    as a plain path string rather than {name, target, kind} — TodoStore must still load
    those, defaulting kind="file" and name to the basename (see _attachment_from_record).
    """
    path = tmp_path / "todos.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": 1,
                    "subject": "Task",
                    "description": "",
                    "done": False,
                    "parent_id": None,
                    "attachments": ["/home/user/notes.txt"],
                }
            ]
        )
    )
    store = TodoStore(path)

    todo = store.get(1)
    assert len(todo.attachments) == 1
    attachment = todo.attachments[0]
    assert attachment.kind == "file"
    assert attachment.target == "/home/user/notes.txt"
    assert attachment.name == "notes.txt"


async def test_file_picker_filters_as_you_type(tmp_path):
    (tmp_path / "alpha.txt").write_text("a")
    (tmp_path / "zzz.log").write_text("z")

    class FilePickerHarness(App):
        def on_mount(self) -> None:
            self.push_screen(FilePickerScreen(root=tmp_path))

    app = FilePickerHarness()
    async with app.run_test() as pilot:
        await pilot.pause()
        results = app.query_one("#results", OptionList)
        assert results.option_count == 2

        for ch in "alpha":
            await pilot.press(ch)
        await pilot.pause()

        assert results.option_count == 1
        assert results.get_option_at_index(0).id.endswith("alpha.txt")


async def _cd(pilot, command: str) -> None:
    # Sets the search Input's value directly rather than simulating individual
    # keypresses: /cd is only acted on at submit time (on_input_submitted), so
    # there's no live-filtering behavior worth exercising character-by-character
    # here (unlike test_file_picker_filters_as_you_type above). This also sidesteps
    # a slow, real Textual quirk — Pilot.press() awaits animator.wait_until_complete()
    # after every keystroke, and once the OptionList's matches hit zero mid-typing
    # (any "/cd ..." partial like "/c" won't substring-match real paths) each further
    # press() pays a ~2s wait; that's a Pilot-only artifact of simulating one key at a
    # time; it doesn't affect real interactive typing.
    pilot.app.screen.query_one("#search", Input).value = command
    await pilot.press("enter")
    await pilot.pause()


async def test_file_picker_cd_narrows_to_subdirectory(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("m")
    (tmp_path / "src" / "utils").mkdir()
    (tmp_path / "src" / "utils" / "helper.py").write_text("h")

    class FilePickerHarness(App):
        def on_mount(self) -> None:
            self.push_screen(FilePickerScreen(root=tmp_path))

    app = FilePickerHarness()
    async with app.run_test() as pilot:
        await pilot.pause()
        results = app.query_one("#results", OptionList)
        assert results.option_count == 5  # a.txt, src, src/main.py, src/utils, src/utils/helper.py

        await _cd(pilot, "/cd src")

        screen = app.screen
        assert isinstance(screen, FilePickerScreen)
        assert screen._cwd == tmp_path / "src"
        assert str(tmp_path / "src") in str(screen.query_one("#picker-title", Static).renderable)
        assert screen.query_one("#search", Input).value == ""

        listed = {str(Path(p).relative_to(screen._cwd)) for p in screen._paths}
        assert listed == {"main.py", "utils", "utils/helper.py"}
        assert results.option_count == 3


async def test_file_picker_cd_dotdot_goes_back_up(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("m")
    (tmp_path / "a.txt").write_text("a")

    class FilePickerHarness(App):
        def on_mount(self) -> None:
            self.push_screen(FilePickerScreen(root=tmp_path))

    app = FilePickerHarness()
    async with app.run_test() as pilot:
        await pilot.pause()
        await _cd(pilot, "/cd src")
        assert app.screen._cwd == tmp_path / "src"

        await _cd(pilot, "/cd ..")
        assert app.screen._cwd == tmp_path


async def test_file_picker_cd_rejects_escaping_root(tmp_path):
    (tmp_path / "a.txt").write_text("a")

    class FilePickerHarness(App):
        def on_mount(self) -> None:
            self.push_screen(FilePickerScreen(root=tmp_path))

    app = FilePickerHarness()
    async with app.run_test() as pilot:
        await pilot.pause()
        await _cd(pilot, "/cd ../../..")

        screen = app.screen
        assert isinstance(screen, FilePickerScreen)
        assert screen._cwd == tmp_path


async def test_file_picker_cd_rejects_non_directory(tmp_path):
    (tmp_path / "a.txt").write_text("a")

    class FilePickerHarness(App):
        def on_mount(self) -> None:
            self.push_screen(FilePickerScreen(root=tmp_path))

    app = FilePickerHarness()
    async with app.run_test() as pilot:
        await pilot.pause()
        await _cd(pilot, "/cd a.txt")

        screen = app.screen
        assert isinstance(screen, FilePickerScreen)
        assert screen._cwd == tmp_path


async def test_file_picker_respects_gitignore(tmp_path):
    (tmp_path / ".gitignore").write_text("build/\n*.log\n!keep.log\n")
    (tmp_path / "keep.log").write_text("keep")
    (tmp_path / "skip.log").write_text("skip")
    (tmp_path / "normal.txt").write_text("normal")
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "artifact.bin").write_text("artifact")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("main")
    (tmp_path / "src" / ".gitignore").write_text("secret.py\n")
    (tmp_path / "src" / "secret.py").write_text("secret")

    class FilePickerHarness(App):
        def on_mount(self) -> None:
            self.push_screen(FilePickerScreen(root=tmp_path))

    app = FilePickerHarness()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, FilePickerScreen)
        listed = {str(Path(p).relative_to(tmp_path)) for p in screen._paths}

        assert listed == {".gitignore", "keep.log", "normal.txt", "src", "src/.gitignore", "src/main.py"}


async def _select(pilot, todo_id) -> None:
    """Move the tree cursor onto the node whose .data == todo_id."""
    tree = pilot.app.query_one(Tree)

    def find(node):
        for child in node.children:
            if child.data == todo_id:
                return child
            found = find(child)
            if found is not None:
                return found
        return None

    node = find(tree.root)
    assert node is not None
    tree.move_cursor(node)
    await pilot.pause()


async def test_organize_mode_up_down_reorder_siblings(tmp_path):
    store = TodoStore(tmp_path / "todos.json")
    a = store.add(subject="A", description="", parent_id=None)
    b = store.add(subject="B", description="", parent_id=None)
    c = store.add(subject="C", description="", parent_id=None)
    app = HarnessApp(store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _select(pilot, b.id)

        await pilot.press("m")
        await pilot.pause()
        await pilot.press("up")
        await pilot.pause()
        assert [t.id for t in store.children_of(None)] == [b.id, a.id, c.id]

        tree = app.query_one(Tree)
        assert tree.cursor_node.data == b.id  # cursor follows the moved node

        await pilot.press("down")
        await pilot.pause()
        assert [t.id for t in store.children_of(None)] == [a.id, b.id, c.id]

        await pilot.press("m")
        await pilot.pause()


async def test_organize_mode_up_noop_when_already_first(tmp_path):
    store = TodoStore(tmp_path / "todos.json")
    a = store.add(subject="A", description="", parent_id=None)
    b = store.add(subject="B", description="", parent_id=None)
    app = HarnessApp(store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _select(pilot, a.id)
        await pilot.press("m")
        await pilot.pause()
        await pilot.press("up")
        await pilot.pause()
        assert [t.id for t in store.children_of(None)] == [a.id, b.id]


async def test_organize_mode_right_indents_under_previous_sibling(tmp_path):
    store = TodoStore(tmp_path / "todos.json")
    a = store.add(subject="A", description="", parent_id=None)
    b = store.add(subject="B", description="", parent_id=None)
    app = HarnessApp(store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _select(pilot, b.id)
        await pilot.press("m")
        await pilot.pause()
        await pilot.press("right")
        await pilot.pause()

        assert [t.id for t in store.children_of(None)] == [a.id]
        assert [t.id for t in store.children_of(a.id)] == [b.id]

        tree = app.query_one(Tree)
        assert tree.cursor_node.data == b.id
        parent_node = tree.root.children[0]
        assert parent_node.data == a.id
        assert [n.data for n in parent_node.children] == [b.id]


async def test_organize_mode_left_outdents_next_to_parent(tmp_path):
    store = TodoStore(tmp_path / "todos.json")
    a = store.add(subject="A", description="", parent_id=None)
    b = store.add(subject="B", description="", parent_id=a.id)
    c = store.add(subject="C", description="", parent_id=None)
    app = HarnessApp(store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _select(pilot, b.id)
        await pilot.press("m")
        await pilot.pause()
        await pilot.press("left")
        await pilot.pause()

        # B becomes a top-level sibling, placed right after its former parent A
        assert [t.id for t in store.children_of(None)] == [a.id, b.id, c.id]
        assert store.children_of(a.id) == []

        tree = app.query_one(Tree)
        assert tree.cursor_node.data == b.id


async def test_organize_mode_right_noop_when_no_previous_sibling(tmp_path):
    store = TodoStore(tmp_path / "todos.json")
    a = store.add(subject="A", description="", parent_id=None)
    app = HarnessApp(store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _select(pilot, a.id)
        await pilot.press("m")
        await pilot.pause()
        await pilot.press("right")
        await pilot.pause()

        assert [t.id for t in store.children_of(None)] == [a.id]


async def test_organize_mode_left_noop_when_already_top_level(tmp_path):
    store = TodoStore(tmp_path / "todos.json")
    a = store.add(subject="A", description="", parent_id=None)
    app = HarnessApp(store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _select(pilot, a.id)
        await pilot.press("m")
        await pilot.pause()
        await pilot.press("left")
        await pilot.pause()

        assert [t.id for t in store.children_of(None)] == [a.id]


async def test_organize_mode_other_key_cancels_and_falls_through(tmp_path):
    store = TodoStore(tmp_path / "todos.json")
    a = store.add(subject="A", description="", parent_id=None)
    app = HarnessApp(store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _select(pilot, a.id)
        await pilot.press("m")
        await pilot.pause()

        pane = app.query_one("TodoPane")
        assert pane._organize_mode is True

        await pilot.press("d")  # unrelated key: cancels organize mode, still deletes
        await pilot.pause()
        assert isinstance(app.screen, ConfirmScreen)
        assert pane._organize_mode is False


async def test_organize_mode_toggle_key_exits_without_falling_through(tmp_path):
    store = TodoStore(tmp_path / "todos.json")
    a = store.add(subject="A", description="", parent_id=None)
    b = store.add(subject="B", description="", parent_id=None)
    app = HarnessApp(store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _select(pilot, a.id)
        await pilot.press("m")
        await pilot.pause()

        pane = app.query_one("TodoPane")
        assert pane._organize_mode is True

        await pilot.press("m")
        await pilot.pause()
        # "m" while active must exit via on_key (stopping the event) rather than
        # falling through to action_toggle_organize_mode, which would re-arm it.
        assert pane._organize_mode is False


async def test_set_redmine_issue_on_any_level(tmp_path):
    store = TodoStore(tmp_path / "todos.json")
    parent = store.add(subject="Project", description="", parent_id=None)
    child = store.add(subject="Fix the widget", description="", parent_id=parent.id)
    app = HarnessApp(store)
    async with app.run_test() as pilot:
        await pilot.pause()
        # cursor starts on the first (parent) node
        await pilot.press("i")
        await pilot.pause()
        assert isinstance(app.screen, todo_pane.RedmineIssueScreen)
        app.screen.query_one("#issue_id", Input).value = "#30568"
        await pilot.click("#save")
        await pilot.pause()

        tree = app.query_one(Tree)
        assert "#30568" in str(tree.cursor_node.label)
        await pilot.press("down")  # child — inherits it
        await pilot.pause()
        assert "#30568 (inherited)" in str(app.query_one("#todo-detail", Static).renderable)

    reloaded = TodoStore(tmp_path / "todos.json")
    assert reloaded.get(parent.id).redmine_issue_id == 30568
    assert reloaded.get(child.id).redmine_issue_id is None
    assert reloaded.effective_redmine_issue(child.id) == 30568


async def test_clearing_redmine_issue(tmp_path):
    store = TodoStore(tmp_path / "todos.json")
    todo = store.add(subject="Fix the widget", description="", parent_id=None)
    store.set_redmine_issue(todo.id, 42)
    app = HarnessApp(store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("i")
        await pilot.pause()
        app.screen.query_one("#issue_id", Input).value = ""
        await pilot.click("#save")
        await pilot.pause()

    assert store.get(todo.id).redmine_issue_id is None
