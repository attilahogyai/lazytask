"""Regression tests for the "f" then "v" vacation-flag combo on the calendar.

"f" arms flag mode (calendar view only), a following "v" toggles the
vacation flag on the cursor-highlighted day. Any other key (or "v" when
flag mode was never armed) must fall through to its normal binding —
in particular plain "v" must keep toggling list/calendar view.
"""

from textual.app import App

from task_log.day_flags import ILLNESS, VACATION, DayFlagStore
from task_log.ui.calendar_view import MonthCalendar
from task_log.ui.time_entries_pane import TimeEntriesScreen

from tests.fakes import FakeDataSource


class HarnessApp(App):
    """Pushes TimeEntriesScreen directly, skipping config/network setup."""

    def __init__(self, datasource: FakeDataSource, flag_store: DayFlagStore) -> None:
        super().__init__()
        self.datasource = datasource
        self.flag_store = flag_store

    def on_mount(self) -> None:
        self.push_screen(TimeEntriesScreen(self.datasource, self.flag_store))


async def test_f_then_v_adds_vacation_flag_to_selected_day(tmp_path):
    store = DayFlagStore(tmp_path / "day_flags.json")
    app = HarnessApp(FakeDataSource(), store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("v")  # switch to calendar view
        await pilot.pause()

        calendar = app.query_one(MonthCalendar)
        day = calendar.date_at(calendar.cursor_coordinate)
        assert day is not None

        await pilot.press("f")
        await pilot.press("v")
        await pilot.pause()

        assert VACATION in store.flags_for(day)
        assert VACATION in calendar._flags.get(day, ())


async def test_f_then_v_again_removes_vacation_flag(tmp_path):
    store = DayFlagStore(tmp_path / "day_flags.json")
    app = HarnessApp(FakeDataSource(), store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("v")
        await pilot.pause()

        calendar = app.query_one(MonthCalendar)
        day = calendar.date_at(calendar.cursor_coordinate)

        await pilot.press("f")
        await pilot.press("v")
        await pilot.pause()
        assert VACATION in store.flags_for(day)

        await pilot.press("f")
        await pilot.press("v")
        await pilot.pause()
        assert VACATION not in store.flags_for(day)


async def test_f_then_i_adds_illness_flag_to_selected_day(tmp_path):
    store = DayFlagStore(tmp_path / "day_flags.json")
    app = HarnessApp(FakeDataSource(), store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("v")  # switch to calendar view
        await pilot.pause()

        calendar = app.query_one(MonthCalendar)
        day = calendar.date_at(calendar.cursor_coordinate)
        assert day is not None

        await pilot.press("f")
        await pilot.press("i")
        await pilot.pause()

        assert ILLNESS in store.flags_for(day)
        assert ILLNESS in calendar._flags.get(day, ())


async def test_f_then_i_again_removes_illness_flag(tmp_path):
    store = DayFlagStore(tmp_path / "day_flags.json")
    app = HarnessApp(FakeDataSource(), store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("v")
        await pilot.pause()

        calendar = app.query_one(MonthCalendar)
        day = calendar.date_at(calendar.cursor_coordinate)

        await pilot.press("f")
        await pilot.press("i")
        await pilot.pause()
        assert ILLNESS in store.flags_for(day)

        await pilot.press("f")
        await pilot.press("i")
        await pilot.pause()
        assert ILLNESS not in store.flags_for(day)


async def test_plain_v_without_f_still_toggles_view(tmp_path):
    store = DayFlagStore(tmp_path / "day_flags.json")
    app = HarnessApp(FakeDataSource(), store)
    async with app.run_test() as pilot:
        await pilot.pause()
        from textual.widgets import ContentSwitcher

        await pilot.press("v")
        await pilot.pause()
        assert app.query_one(ContentSwitcher).current == "calendar-view"

        await pilot.press("v")
        await pilot.pause()
        assert app.query_one(ContentSwitcher).current == "entries"


async def test_f_then_unrelated_key_cancels_flag_mode_without_flagging(tmp_path):
    store = DayFlagStore(tmp_path / "day_flags.json")
    app = HarnessApp(FakeDataSource(), store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("v")  # switch to calendar view
        await pilot.pause()

        calendar = app.query_one(MonthCalendar)
        day = calendar.date_at(calendar.cursor_coordinate)

        await pilot.press("f")
        await pilot.press("f5")  # unrelated key: cancels flag mode, still refreshes
        await pilot.pause()

        assert VACATION not in store.flags_for(day)


async def test_flag_day_disabled_outside_calendar_view(tmp_path):
    store = DayFlagStore(tmp_path / "day_flags.json")
    app = HarnessApp(FakeDataSource(), store)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert screen.check_action("flag_day", ()) is False
