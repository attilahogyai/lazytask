"""Local, backend-independent per-day flags (vacation, etc.).

Flags are not a Redmine concept — they're personal annotations kept in a
small JSON file next to config.toml, loaded eagerly and saved on every
toggle.
"""

import json
from datetime import date
from pathlib import Path

VACATION = "vacation"

FLAG_STYLES: dict[str, str] = {
    VACATION: "on dark_green",
}


class DayFlagStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._flags: dict[date, set[str]] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        data = json.loads(self._path.read_text())
        self._flags = {date.fromisoformat(day): set(flags) for day, flags in data.items()}

    def _save(self) -> None:
        data = {day.isoformat(): sorted(flags) for day, flags in self._flags.items() if flags}
        self._path.write_text(json.dumps(data, indent=2))

    def flags_for(self, day: date) -> frozenset[str]:
        return frozenset(self._flags.get(day, ()))

    def all_flags(self) -> dict[date, frozenset[str]]:
        return {day: frozenset(flags) for day, flags in self._flags.items() if flags}

    def toggle(self, day: date, flag: str) -> frozenset[str]:
        current = self._flags.setdefault(day, set())
        if flag in current:
            current.discard(flag)
        else:
            current.add(flag)
        if not current:
            del self._flags[day]
        self._save()
        return self.flags_for(day)
