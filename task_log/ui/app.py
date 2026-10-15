from pathlib import Path

from textual.app import App
from textual.widgets import Footer, Header, TabbedContent, TabPane

from task_log.config import load_config
from task_log.day_flags import DayFlagStore
from task_log.factory import build_datasource
from task_log.task_entries import TaskEntryStore
from task_log.todos import TodoStore
from task_log.ui.settings_pane import SettingsPane
from task_log.ui.task_entries_pane import TaskEntriesPane
from task_log.ui.time_entries_pane import TimeEntriesPane
from task_log.ui.todo_pane import TodoPane


class TaskLogApp(App):
    BINDINGS = [
        ("ctrl+right", "next_tab", "Next tab"),
        ("ctrl+left", "prev_tab", "Prev tab"),
    ]

    def __init__(self, config_path: Path):
        super().__init__()
        cfg = load_config(config_path)
        self._datasource = build_datasource(cfg)
        self._flag_store = DayFlagStore(Path("day_flags.json"))
        self._todo_store = TodoStore(Path("todos.json"))
        self._task_store = TaskEntryStore(Path("task_entries.json"))
        self._attachments_root = cfg.attachments_root
        self._owner_id = cfg.user_id
        self._owner_name = cfg.user_name

    def compose(self):
        yield Header()
        with TabbedContent(initial="time-entries"):
            with TabPane("Time Entries", id="time-entries"):
                yield TimeEntriesPane(self._datasource, self._flag_store)
            with TabPane("Task Entries", id="task-entries"):
                yield TaskEntriesPane(
                    self._datasource,
                    self._todo_store,
                    self._task_store,
                    self._flag_store,
                    owner_id=self._owner_id,
                    owner_name=self._owner_name,
                )
            with TabPane("Todos", id="todos"):
                yield TodoPane(self._todo_store, attachments_root=self._attachments_root)
            with TabPane("Settings", id="Settings"):
                yield SettingsPane(self._attachments_root)
        yield Footer()

    def on_mount(self) -> None:
        # AUTO_FOCUS is deliberately left at its App default ("*") rather than
        # pinned to "#entries" here: Screen.AUTO_FOCUS falls back to
        # App.AUTO_FOCUS whenever unset, and every modal (EditEntryScreen,
        # TodoEditScreen, ConfirmScreen, FilePickerScreen, ...) leaves its own
        # AUTO_FOCUS unset too — pinning it at the App level would silently
        # break auto-focus in all of them. Focus #entries once, explicitly,
        # instead.
        self.query_one("#time-entries #entries").focus()

    def _tab_ids(self) -> list[str]:
        return [pane.id for pane in self.query(TabPane)]

    def action_next_tab(self) -> None:
        tabs = self.query_one(TabbedContent)
        ids = self._tab_ids()
        tabs.active = ids[(ids.index(tabs.active) + 1) % len(ids)]

    def action_prev_tab(self) -> None:
        tabs = self.query_one(TabbedContent)
        ids = self._tab_ids()
        tabs.active = ids[(ids.index(tabs.active) - 1) % len(ids)]

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        if event.pane.id == "time-entries":
            # Day flags are shared with the Task Entries tab — pick up changes made there.
            self.query_one(TimeEntriesPane).refresh_flags()
            self.query_one("#time-entries #entries").focus()
        elif event.pane.id == "task-entries":
            # Local-only reload (no network): picks up todo/issue changes from the
            # Todos tab and day flags from the Time Entries tab.
            pane = self.query_one(TaskEntriesPane)
            pane.refresh_flags()
            pane.action_refresh_entries()
            self.query_one("#task-entries #entries").focus()
        elif event.pane.id == "todos":
            self.query_one("#todo-tree").focus()
        elif event.pane.id == "Settings":
            self.query_one("#menu-info").focus()
