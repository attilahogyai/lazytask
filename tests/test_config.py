"""load_config has no UI surface to drive, so it's tested directly rather
than through a Pilot — unlike the rest of this suite.
"""

from pathlib import Path

from task_log.config import load_config

_REDMINE_TOML = """
[redmine]
base_url = "https://example.test/"
project_identifier = "proj"
api_key = "key"
"""


def test_attachments_root_defaults_to_cwd_when_unset(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / "config.toml"
    config_path.write_text('[general]\nbackend = "redmine"\n' + _REDMINE_TOML)

    cfg = load_config(config_path)

    assert cfg.attachments_root == Path.cwd()


def test_attachments_root_reads_configured_value(tmp_path):
    attachments_dir = tmp_path / "attachments"
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f'[general]\nbackend = "redmine"\nattachments_root = "{attachments_dir}"\n' + _REDMINE_TOML
    )

    cfg = load_config(config_path)

    assert cfg.attachments_root == attachments_dir


def test_user_id_and_user_name_default_to_none_when_unset(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text('[general]\nbackend = "redmine"\n' + _REDMINE_TOML)

    cfg = load_config(config_path)

    assert cfg.user_id is None
    assert cfg.user_name is None


def test_user_id_and_user_name_read_configured_values(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[general]\nbackend = "redmine"\nuser_id = "ahogyai"\nuser_name = "Hogyai Attila"\n'
        + _REDMINE_TOML
    )

    cfg = load_config(config_path)

    assert cfg.user_id == "ahogyai"
    assert cfg.user_name == "Hogyai Attila"
