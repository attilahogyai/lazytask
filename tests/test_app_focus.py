"""Regression test for a real bug: TaskLogApp used to pin AUTO_FOCUS = "#entries"
at the App level. Screen.AUTO_FOCUS falls back to App.AUTO_FOCUS whenever a
screen leaves its own unset — which every modal here does — so that pin
silently broke auto-focus in EditEntryScreen, TodoEditScreen, and
FilePickerScreen (nothing had focus until you Tab'd manually). This only
shows up when testing the real TaskLogApp; the per-screen test harnesses in
the other test files default to App.AUTO_FOCUS = "*" and don't reproduce it.
"""

from pathlib import Path

from textual.app import App
from textual.widgets import Input, Select

from task_log.day_flags import DayFlagStore
from task_log.task_entries import TaskEntryStore
from task_log.todos import TodoStore
from task_log.ui.app import TaskLogApp
from task_log.ui.edit_screen import EditEntryScreen
from task_log.ui.todo_pane import TodoEditScreen

from tests.fakes import FakeDataSource


class RealApp(TaskLogApp):
    """TaskLogApp with config/network loading swapped for fakes + tmp_path stores."""

    def __init__(self, tmp_path: Path) -> None:
        App.__init__(self)
        self._datasource = FakeDataSource()
        self._flag_store = DayFlagStore(tmp_path / "day_flags.json")
        self._todo_store = TodoStore(tmp_path / "todos.json")
        self._task_store = TaskEntryStore(tmp_path / "task_entries.json")
        self._owner_id = None
        self._owner_name = None
        self._attachments_root = tmp_path


async def test_initial_focus_lands_on_entries_table(tmp_path):
    app = RealApp(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.focused is app.query_one("#entries")


async def test_add_entry_modal_autofocuses_first_field(tmp_path):
    app = RealApp(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        assert isinstance(app.screen, EditEntryScreen)
        # "#project" Select is the first focusable widget in the form.
        assert app.focused is app.screen.query_one("#project", Select)


async def test_todo_edit_modal_autofocuses_subject_input(tmp_path):
    app = RealApp(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+right")  # Task Entries tab
        await pilot.press("ctrl+right")  # Todos tab
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        assert isinstance(app.screen, TodoEditScreen)
        assert app.focused is app.screen.query_one("#subject", Input)


async def test_settings_tab_shows_attachments_root(tmp_path):
    app = RealApp(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+right")  # Task Entries
        await pilot.press("ctrl+right")  # Todos
        await pilot.press("ctrl+right")  # Settings
        await pilot.pause()

        from textual.widgets import Static

        assert str(tmp_path) in str(app.query_one("#menu-info", Static).renderable)


async def test_task_entries_tab_focuses_its_own_table(tmp_path):
    app = RealApp(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+right")  # Task Entries
        await pilot.pause()
        assert app.focused is app.query_one("#task-entries #entries")
