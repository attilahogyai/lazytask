from pathlib import Path

from textual.containers import Vertical
from textual.widgets import Button, Static


class SettingsPane(Vertical):
    """App-level info + Exit — a place for settings that aren't tied to one tab.

    Currently just shows the configured attachment root (read-only: it comes
    from config.toml's [general].attachments_root and only takes effect on
    the next restart, so there's nothing here to edit live).
    """

    DEFAULT_CSS = """
    SettingsPane {
        align: center top;
        padding: 2 4;
    }
    #menu-info {
        margin-bottom: 2;
    }
    """

    BINDINGS = []

    def __init__(self, attachments_root: Path) -> None:
        super().__init__()
        self._attachments_root = attachments_root

    def compose(self):
        yield Static(
            f"Todo attachment root: {self._attachments_root}\n"
            "Configured via [general].attachments_root in config.toml — "
            "edit the file and restart to change it.",
            id="menu-info",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        pass        
