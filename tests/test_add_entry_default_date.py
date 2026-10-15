"""Regression tests for the "a" (add entry) default spent_on date.

List view has no day context, so it should default to today. Calendar view
has a cursor-highlighted day, so a new entry should default to *that* day,
not today — including after paging to a different month.
"""

from datetime import date

from textual.app import App
from textual.widgets import Input

from task_log.ui.calendar_view import MonthCalendar
from task_log.ui.edit_screen import EditEntryScreen
from task_log.ui.time_entries_pane import TimeEntriesScreen

from tests.fakes import FakeDataSource


class HarnessApp(App):
    """Pushes TimeEntriesScreen directly, skipping config/network setup."""

    def __init__(self, datasource: FakeDataSource) -> None:
        super().__init__()
        self.datasource = datasource

    def on_mount(self) -> None:
        self.push_screen(TimeEntriesScreen(self.datasource))


async def test_add_entry_in_list_view_defaults_to_today():
    app = HarnessApp(FakeDataSource())
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()

        screen = app.screen
        assert isinstance(screen, EditEntryScreen)
        assert screen.query_one("#spent_on", Input).value == date.today().isoformat()


async def test_add_entry_in_calendar_view_defaults_to_selected_day():
    app = HarnessApp(FakeDataSource())
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("v")  # switch to calendar view
        await pilot.pause()

        calendar = app.query_one(MonthCalendar)
        await pilot.press("down")
        await pilot.press("right")
        await pilot.pause()
        selected_day = calendar.date_at(calendar.cursor_coordinate)
        assert selected_day is not None

        await pilot.press("a")
        await pilot.pause()

        screen = app.screen
        assert isinstance(screen, EditEntryScreen)
        assert screen.query_one("#spent_on", Input).value == selected_day.isoformat()


async def test_add_entry_in_calendar_view_uses_selected_day_after_month_navigation():
    app = HarnessApp(FakeDataSource())
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("v")  # switch to calendar view
        await pilot.pause()
        await pilot.press("p")  # previous month
        await pilot.pause()

        calendar = app.query_one(MonthCalendar)
        await pilot.press("down")
        await pilot.press("down")
        await pilot.pause()
        selected_day = calendar.date_at(calendar.cursor_coordinate)
        assert selected_day is not None
        assert selected_day.month != date.today().month or selected_day.year != date.today().year

        await pilot.press("a")
        await pilot.pause()

        screen = app.screen
        assert isinstance(screen, EditEntryScreen)
        assert screen.query_one("#spent_on", Input).value == selected_day.isoformat()
