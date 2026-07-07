from pathlib import Path

from textual.app import App

from task_log.config import load_config
from task_log.factory import build_datasource
from task_log.ui.screens import TimeEntriesScreen


class TaskLogApp(App):
    def __init__(self, config_path: Path):
        super().__init__()
        self._config_path = config_path

    def on_mount(self) -> None:
        cfg = load_config(self._config_path)
        datasource = build_datasource(cfg)
        self.push_screen(TimeEntriesScreen(datasource))
