from task_log.config import AppConfig
from task_log.datasource import DataSource
from task_log.redmine.client import RedmineClient


def build_datasource(cfg: AppConfig) -> DataSource:
    if cfg.backend == "redmine":
        return RedmineClient(cfg.redmine)
    raise ValueError(f"Unknown backend: {cfg.backend}")
