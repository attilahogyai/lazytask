from pathlib import Path

from task_log.ui.app import TaskLogApp


def main():
    TaskLogApp(Path("config.toml")).run()


if __name__ == "__main__":
    main()
