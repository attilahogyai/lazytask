import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RedmineConfig:
    base_url: str
    project_identifier: str
    api_key: str


@dataclass(frozen=True)
class AppConfig:
    backend: str
    redmine: RedmineConfig
    attachments_root: Path
    user_id: str | None
    user_name: str | None


def load_config(path: Path) -> AppConfig:
    with path.open("rb") as f:
        data = tomllib.load(f)
    r = data["redmine"]
    general = data["general"]
    attachments_root = (
        Path(general["attachments_root"]).expanduser()
        if "attachments_root" in general
        else Path.cwd()
    )
    return AppConfig(
        backend=general["backend"],
        redmine=RedmineConfig(
            base_url=r["base_url"].rstrip("/"),
            project_identifier=r["project_identifier"],
            api_key=r["api_key"],
        ),
        attachments_root=attachments_root,
        user_id=general.get("user_id"),
        user_name=general.get("user_name"),
    )
