import calendar
from collections import defaultdict
from datetime import date

from rich.text import Text
from textual.message import Message
from textual.widgets import DataTable

from task_log.day_flags import FLAG_STYLES
from task_log.models import TimeEntry

_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_DAY_COLUMN_WIDTH = 12
_DAY_CONTENT_WIDTH = _DAY_COLUMN_WIDTH - 2  # minus DataTable's default 1-cell padding per side


class MonthCalendar(DataTable):
    """Month grid where each day cell shows total hours and entry count."""

    DEFAULT_CSS = """
    MonthCalendar {
        border: round $accent;
        border-title-align: center;
        height: auto;
    }
    """

    class DaySelected(Message):
        """Posted whenever the cursor lands on a day cell."""

        def __init__(self, day: date) -> None:
            self.day = day
            super().__init__()

    def __init__(self, **kwargs) -> None:
        super().__init__(cursor_type="cell", **kwargs)
        today = date.today()
        self._year = today.year
        self._month = today.month
        self._entries: list[TimeEntry] = []
        self._weeks: list[list[date]] = []
        self._flags: dict[date, frozenset[str]] = {}

    def set_entries(self, entries: list[TimeEntry]) -> None:
        self._entries = entries
        self._rebuild()

    def set_flags(self, flags: dict[date, frozenset[str]]) -> None:
        self._flags = flags
        self._rebuild()

    def move_month(self, delta: int) -> None:
        index = self._year * 12 + (self._month - 1) + delta
        self._year, month0 = divmod(index, 12)
        self._month = month0 + 1
        self._rebuild()

    def goto_today(self) -> None:
        today = date.today()
        self._year, self._month = today.year, today.month
        self._rebuild(select=today)

    def on_mount(self) -> None:
        self._rebuild()

    def date_at(self, coordinate) -> date | None:
        row, col = coordinate
        if 0 <= row < len(self._weeks) and 0 <= col < 7:
            return self._weeks[row][col]
        return None

    def on_data_table_cell_highlighted(self, event: DataTable.CellHighlighted) -> None:
        day = self.date_at(event.coordinate)
        if day is not None:
            self.post_message(self.DaySelected(day))

    def _rebuild(self, select: date | None = None) -> None:
        previous = select or (self.date_at(self.cursor_coordinate) if self._weeks else None)
        self.clear(columns=True)
        for label in _WEEKDAYS:
            self.add_column(label, width=12)

        hours: defaultdict[date, float] = defaultdict(float)
        counts: defaultdict[date, int] = defaultdict(int)
        for e in self._entries:
            hours[e.spent_on] += e.hours
            counts[e.spent_on] += 1

        today = date.today()
        self._weeks = calendar.Calendar().monthdatescalendar(self._year, self._month)
        for week in self._weeks:
            cells = []
            for day in week:
                outside = day.month != self._month
                flag_style = next(
                    (style for flag, style in FLAG_STYLES.items() if flag in self._flags.get(day, ())),
                    None,
                )
                text = Text(style=flag_style or "")
                if day == today:
                    day_style = "bold reverse"
                else:
                    day_style = "dim" if outside else "bold"
                header = f"{day.day:>2}"
                header_pad = " " * (_DAY_CONTENT_WIDTH - len(header)) if flag_style else ""
                text.append(header + header_pad, style=day_style)
                if day in hours:
                    hours_part = f"{hours[day]:g}h"
                    count_part = f" · {counts[day]}"
                    count_pad = (
                        " " * max(_DAY_CONTENT_WIDTH - len(hours_part) - len(count_part), 0)
                        if flag_style
                        else ""
                    )
                    text.append(f"\n{hours_part}", style="dim" if outside else "green")
                    text.append(count_part + count_pad, style="dim")
                elif flag_style:
                    text.append("\n" + " " * _DAY_CONTENT_WIDTH, style="dim")
                cells.append(text)
            self.add_row(*cells, height=2)

        self.border_title = f"{calendar.month_name[self._month]} {self._year}"

        # keep the cursor on the previously selected day if it is still visible,
        # otherwise land on today when showing the current month
        target = None
        if previous is not None and any(previous in week for week in self._weeks):
            target = previous
        elif any(today in week for week in self._weeks):
            target = today
        if target is not None:
            for row, week in enumerate(self._weeks):
                if target in week:
                    self.move_cursor(row=row, column=week.index(target))
                    break
        day = self.date_at(self.cursor_coordinate)
        if day is not None:
            self.post_message(self.DaySelected(day))
