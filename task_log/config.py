import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RedmineConfig:
    base_url: str
    project_identifier: str
    username: str
    password: str


@dataclass(frozen=True)
class AppConfig:
    backend: str
    redmine: RedmineConfig


def load_config(path: Path) -> AppConfig:
    with path.open("rb") as f:
        data = tomllib.load(f)
    r = data["redmine"]
    return AppConfig(
        backend=data["general"]["backend"],
        redmine=RedmineConfig(
            base_url=r["base_url"].rstrip("/"),
            project_identifier=r["project_identifier"],
            username=r["username"],
            password=r["password"],
        ),
    )
