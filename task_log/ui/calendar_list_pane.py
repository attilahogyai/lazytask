"""Shared list/calendar mechanics for the Time Entries and Task Entries tabs.

Both tabs look and behave the same: a "#filters" bar, then a ContentSwitcher
between a flat "#entries" DataTable and a MonthCalendar with a "#day-entries"
panel for the highlighted day, plus month navigation and day-flag mode.
Subclasses supply the filter widgets, the columns, how one entry renders as a
row, and how entries are loaded/filtered into self._filtered_entries.
"""

from datetime import date

from textual import events
from textual.containers import Horizontal, Vertical
from textual.widgets import ContentSwitcher, DataTable

from task_log.day_flags import ILLNESS, VACATION, DayFlagStore
from task_log.ui.calendar_view import MonthCalendar

_FLAG_KEYS = {"v": VACATION, "i": ILLNESS}


class CalendarListPane(Vertical):
    DEFAULT_CSS = """
    #filters {
        height: auto;
    }
    #filters Select {
        width: 40;
    }
    #day-entries {
        border: round $accent;
        border-title-align: center;
        height: 1fr;
    }
    """

    BINDINGS = [
        ("f5", "refresh_entries", "Refresh"),
        ("v", "toggle_view", "List/Calendar"),
        ("p", "prev_month", "Prev month"),
        ("n", "next_month", "Next month"),
        ("t", "this_month", "This month"),
        ("f", "flag_day", "Flag day"),
    ]

    # Column headers for "#entries"; "#day-entries" shows the same minus "Date".
    COLUMNS: tuple[str, ...] = ()

    def __init__(self, flag_store: DayFlagStore):
        super().__init__()
        self._flag_store = flag_store
        self._filtered_entries: list = []
        self._flag_pending = False
        self._shown_day: date | None = None

    def compose_filters(self):
        yield from ()

    def compose(self):
        with Horizontal(id="filters"):
            yield from self.compose_filters()
        with ContentSwitcher(initial="entries", id="views"):
            yield DataTable(id="entries")
            with Vertical(id="calendar-view"):
                yield MonthCalendar(id="calendar")
                yield DataTable(id="day-entries", cursor_type="row")

    def on_mount(self) -> None:
        self.query_one("#entries", DataTable).add_columns("Date", *self.COLUMNS)
        self.query_one("#day-entries", DataTable).add_columns(*self.COLUMNS)
        self.refresh_flags()
        self._load_entries()

    def _load_entries(self) -> None:
        raise NotImplementedError

    def _row(self, entry) -> tuple:
        """One entry's cells for COLUMNS (no Date)."""
        raise NotImplementedError

    def refresh_flags(self) -> None:
        # The DayFlagStore is shared between tabs — re-read it when this one is shown.
        self.query_one(MonthCalendar).set_flags(self._flag_store.all_flags())

    def _render_entries(self) -> None:
        """Push self._filtered_entries into the list table and the calendar."""
        table = self.query_one("#entries", DataTable)
        # clear() resets the cursor to the top — keep it where it was so a reload
        # (after an edit, a Redmine sync, ...) doesn't lose your place.
        row = table.cursor_row
        table.clear()
        for e in self._filtered_entries:
            table.add_row(e.spent_on.isoformat(), *self._row(e))
        table.move_cursor(row=min(row, table.row_count - 1), animate=False)
        self.query_one(MonthCalendar).set_entries(self._filtered_entries)

    @property
    def _in_calendar(self) -> bool:
        try:
            return self.query_one(ContentSwitcher).current == "calendar-view"
        except Exception:
            return False

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action in ("prev_month", "next_month", "this_month", "flag_day") and not self._in_calendar:
            return False
        return True

    def _calendar_day(self) -> date | None:
        """The cursor-highlighted calendar day, or None in list view."""
        if not self._in_calendar:
            return None
        calendar = self.query_one(MonthCalendar)
        return calendar.date_at(calendar.cursor_coordinate)

    def _entry_under_cursor(self):
        if self._in_calendar:
            day = self._calendar_day()
            day_entries = [e for e in self._filtered_entries if e.spent_on == day]
            row = self.query_one("#day-entries", DataTable).cursor_row
            return day_entries[row] if 0 <= row < len(day_entries) else None
        row = self.query_one("#entries", DataTable).cursor_row
        return self._filtered_entries[row] if 0 <= row < len(self._filtered_entries) else None

    def action_refresh_entries(self) -> None:
        self._load_entries()

    def action_toggle_view(self) -> None:
        switcher = self.query_one(ContentSwitcher)
        if self._in_calendar:
            switcher.current = "entries"
            self.query_one("#entries").focus()
        else:
            switcher.current = "calendar-view"
            self.query_one(MonthCalendar).focus()
        self.refresh_bindings()

    def action_prev_month(self) -> None:
        self.query_one(MonthCalendar).move_month(-1)

    def action_next_month(self) -> None:
        self.query_one(MonthCalendar).move_month(1)

    def action_this_month(self) -> None:
        self.query_one(MonthCalendar).goto_today()

    def action_flag_day(self) -> None:
        self._flag_pending = True
        self.notify("Flag: press v for vacation, i for illness")

    def on_key(self, event: events.Key) -> None:
        if not self._flag_pending:
            return
        self._flag_pending = False
        flag = _FLAG_KEYS.get(event.key)
        if flag is None:
            return
        event.stop()
        day = self._calendar_day()
        if day is None:
            return
        flags = self._flag_store.toggle(day, flag)
        self.refresh_flags()
        verb = "added to" if flag in flags else "removed from"
        self.notify(f"{flag.capitalize()} flag {verb} {day.isoformat()}")

    def on_month_calendar_day_selected(self, message: MonthCalendar.DaySelected) -> None:
        self._show_day(message.day)

    def _show_day(self, day: date) -> None:
        table = self.query_one("#day-entries", DataTable)
        # Same day re-rendered (a reload) keeps the cursor; a different day starts at the top.
        row = table.cursor_row if day == self._shown_day else 0
        self._shown_day = day
        table.clear()
        day_entries = [e for e in self._filtered_entries if e.spent_on == day]
        for e in day_entries:
            table.add_row(*self._row(e))
        table.move_cursor(row=min(row, table.row_count - 1), animate=False)
        if day_entries:
            total = sum(e.hours for e in day_entries)
            table.border_title = f"{day.isoformat()} — {total:g}h in {len(day_entries)} entries"
        else:
            table.border_title = f"{day.isoformat()} — no entries"
