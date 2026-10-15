"""Regression tests for the Task Entries tab (task_log/ui/task_entries_pane.py):
hours logged against a todo leaf, mirrored to a Redmine time entry whenever the
todo — or its nearest ancestor — has a Redmine issue attached ("a" adds, "e"
edits, "d" deletes, "r" syncs the entry under the cursor to Redmine). See CLAUDE.md's
task_entries_pane.py / edit_screen.py notes for the sync design.
"""

from datetime import date, timedelta

from textual.app import App
from textual.widgets import DataTable, Input, Select

from task_log.day_flags import DayFlagStore
from task_log.models import Activity, TimeEntry
from task_log.task_entries import GENERAL_ACTIVITY, TaskEntryStore
from task_log.todos import TodoStore
from task_log.ui.edit_screen import TaskEntryEditScreen
from task_log.ui.task_entries_pane import TaskEntriesScreen
from task_log.ui.time_entries_pane import TimeEntriesScreen
from task_log.ui.todo_pane import ConfirmScreen

from tests.fakes import FakeDataSource


class HarnessApp(App):
    """Pushes TaskEntriesScreen directly, skipping config/network setup."""

    def __init__(
        self,
        datasource: FakeDataSource,
        todo_store: TodoStore,
        task_store: TaskEntryStore,
        flag_store: DayFlagStore | None = None,
        owner_id: str | None = None,
        owner_name: str | None = None,
    ) -> None:
        super().__init__()
        self.datasource = datasource
        self.todo_store = todo_store
        self.task_store = task_store
        self.flag_store = flag_store
        self.owner_id = owner_id
        self.owner_name = owner_name

    def on_mount(self) -> None:
        self.push_screen(
            TaskEntriesScreen(
                self.datasource,
                self.todo_store,
                self.task_store,
                self.flag_store,
                owner_id=self.owner_id,
                owner_name=self.owner_name,
            )
        )


def _store_pair(tmp_path):
    todo_store = TodoStore(tmp_path / "todos.json")
    task_store = TaskEntryStore(tmp_path / "task_entries.json")
    return todo_store, task_store


async def _add_entry(pilot, hours="2.5"):
    await pilot.press("a")
    await pilot.pause()
    screen = pilot.app.screen
    assert isinstance(screen, TaskEntryEditScreen)
    screen.query_one("#hours", Input).value = hours
    await pilot.click("#save")
    await pilot.pause()
    return screen


async def test_add_task_entry_without_issue_stays_local(tmp_path):
    todo_store, task_store = _store_pair(tmp_path)
    todo = todo_store.add(subject="Fix the widget", description="", parent_id=None)
    ds = FakeDataSource()
    app = HarnessApp(ds, todo_store, task_store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, TaskEntryEditScreen)
        assert screen.query_one("#todo", Select).value == todo.id
        assert screen.query_one("#activity", Select).value == "Development"  # FakeDataSource's is_default
        screen.query_one("#hours", Input).value = "2.5"
        await pilot.click("#save")
        await pilot.pause()

    [entry] = task_store.all()
    assert entry.todo_id == todo.id
    assert entry.hours == 2.5
    assert entry.redmine_entry_id is None
    assert ds.created == []


async def test_add_task_entry_with_inherited_issue_logs_to_redmine_and_links_id(tmp_path):
    todo_store, task_store = _store_pair(tmp_path)
    parent = todo_store.add(subject="Project", description="", parent_id=None)
    todo_store.set_redmine_issue(parent.id, 30568)
    leaf = todo_store.add(subject="Fix the widget", description="", parent_id=parent.id)
    ds = FakeDataSource()
    app = HarnessApp(ds, todo_store, task_store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _add_entry(pilot, hours="2.5")

    [created] = ds.created
    assert created["issue_id"] == 30568
    assert created["hours"] == 2.5
    assert created["project_id"] == 90
    assert created["activity_id"] == 1  # GENERAL_ACTIVITY -> Redmine's default activity
    [entry] = task_store.all()
    assert entry.todo_id == leaf.id
    assert entry.redmine_entry_id == created["id"]


async def test_todo_dropdown_shows_full_path_from_top_level(tmp_path):
    # A leaf subject alone doesn't say which project it belongs to.
    todo_store, task_store = _store_pair(tmp_path)
    top = todo_store.add(subject="Project", description="", parent_id=None)
    middle = todo_store.add(subject="Feature", description="", parent_id=top.id)
    todo_store.add(subject="Fix the widget", description="", parent_id=middle.id)
    ds = FakeDataSource()
    app = HarnessApp(ds, todo_store, task_store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        select = app.screen.query_one("#todo", Select)
        labels = [str(prompt) for prompt, _ in select._options]
        assert "Project › Feature › Fix the widget" in labels


async def test_nearest_issue_in_the_tree_wins(tmp_path):
    todo_store, task_store = _store_pair(tmp_path)
    top = todo_store.add(subject="Project", description="", parent_id=None)
    todo_store.set_redmine_issue(top.id, 100)
    middle = todo_store.add(subject="Feature", description="", parent_id=top.id)
    todo_store.set_redmine_issue(middle.id, 200)
    todo_store.add(subject="Fix the widget", description="", parent_id=middle.id)
    ds = FakeDataSource()
    app = HarnessApp(ds, todo_store, task_store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _add_entry(pilot)

    assert ds.created[0]["issue_id"] == 200


async def test_redmine_activity_name_maps_to_its_id(tmp_path):
    todo_store, task_store = _store_pair(tmp_path)
    todo = todo_store.add(subject="Fix the widget", description="", parent_id=None)
    todo_store.set_redmine_issue(todo.id, 1)
    activities = [
        Activity(id=1, name="Development", is_default=True),
        Activity(id=2, name="Design", is_default=False),
    ]
    ds = FakeDataSource(activities=activities)
    app = HarnessApp(ds, todo_store, task_store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        screen = app.screen
        activity_select = screen.query_one("#activity", Select)
        assert [value for _, value in activity_select._options] == [
            GENERAL_ACTIVITY,
            "Development",
            "Design",
        ]
        activity_select.value = "Design"
        screen.query_one("#hours", Input).value = "1"
        await pilot.click("#save")
        await pilot.pause()

    assert task_store.all()[0].activity == "Design"
    assert ds.created[0]["activity_id"] == 2


async def test_fejlesztes_is_the_default_activity_when_redmine_flags_none(tmp_path):
    # The real Redmine instance has no is_default activity: new entries preselect
    # Fejlesztés, and GENERAL_ACTIVITY syncs as Fejlesztés too (not the first one).
    todo_store, task_store = _store_pair(tmp_path)
    todo = todo_store.add(subject="Fix the widget", description="", parent_id=None)
    todo_store.set_redmine_issue(todo.id, 1)
    task_store.add(
        todo_id=todo.id, spent_on=date.today(), hours=1.0, activity=GENERAL_ACTIVITY, comments=""
    )
    ds = FakeDataSource(
        activities=[
            Activity(id=8, name="Tervezés", is_default=False),
            Activity(id=9, name="Fejlesztés", is_default=False),
        ]
    )
    app = HarnessApp(ds, todo_store, task_store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("r")
        await pilot.pause()
        assert ds.created[0]["activity_id"] == 9

        await pilot.press("a")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, TaskEntryEditScreen)
        assert screen.query_one("#activity", Select).value == "Fejlesztés"


async def test_redmine_failure_keeps_form_open_and_saves_nothing(tmp_path):
    todo_store, task_store = _store_pair(tmp_path)
    todo = todo_store.add(subject="Fix the widget", description="", parent_id=None)
    todo_store.set_redmine_issue(todo.id, 1)
    ds = FakeDataSource()

    def fail(**_):
        raise RuntimeError("boom")

    ds.create_time_entry = fail
    app = HarnessApp(ds, todo_store, task_store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _add_entry(pilot)
        assert isinstance(app.screen, TaskEntryEditScreen)

    assert task_store.all() == []


async def test_edit_linked_entry_updates_redmine_entry(tmp_path):
    todo_store, task_store = _store_pair(tmp_path)
    todo = todo_store.add(subject="Fix the widget", description="", parent_id=None)
    todo_store.set_redmine_issue(todo.id, 42)
    entry = task_store.add(
        todo_id=todo.id,
        spent_on=date.today(),
        hours=1.0,
        activity=GENERAL_ACTIVITY,
        comments="",
        redmine_entry_id=777,
    )
    ds = FakeDataSource()
    app = HarnessApp(ds, todo_store, task_store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("e")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, TaskEntryEditScreen)
        screen.query_one("#hours", Input).value = "3"
        await pilot.click("#save")
        await pilot.pause()

    assert task_store.get(entry.id).hours == 3.0
    assert task_store.get(entry.id).redmine_entry_id == 777
    assert ds.created == []
    [updated] = ds.updated
    assert updated["entry_id"] == 777
    assert updated["hours"] == 3.0
    assert updated["issue_id"] == 42


async def test_edit_unlinked_entry_after_issue_attached_creates_redmine_entry(tmp_path):
    todo_store, task_store = _store_pair(tmp_path)
    todo = todo_store.add(subject="Fix the widget", description="", parent_id=None)
    entry = task_store.add(
        todo_id=todo.id, spent_on=date.today(), hours=1.0, activity=GENERAL_ACTIVITY, comments=""
    )
    todo_store.set_redmine_issue(todo.id, 42)
    ds = FakeDataSource()
    app = HarnessApp(ds, todo_store, task_store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("e")
        await pilot.pause()
        await pilot.click("#save")
        await pilot.pause()

    assert task_store.get(entry.id).redmine_entry_id == ds.created[0]["id"]


async def test_sync_key_creates_redmine_entry_and_fills_redmine_column(tmp_path):
    todo_store, task_store = _store_pair(tmp_path)
    parent = todo_store.add(subject="Project", description="", parent_id=None)
    todo_store.set_redmine_issue(parent.id, 42)
    todo = todo_store.add(subject="Fix the widget", description="", parent_id=parent.id)
    entry = task_store.add(
        todo_id=todo.id, spent_on=date(2026, 10, 13), hours=6.0, activity=GENERAL_ACTIVITY, comments="hi"
    )
    ds = FakeDataSource()
    app = HarnessApp(ds, todo_store, task_store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("r")
        await pilot.pause()
        [created] = ds.created
        assert created["issue_id"] == 42
        assert created["spent_on"] == date(2026, 10, 13)
        assert created["hours"] == 6.0
        assert created["comments"] == "hi"
        assert task_store.get(entry.id).redmine_entry_id == created["id"]
        row = app.query_one("#entries", DataTable).get_row_at(0)
        assert row[-1] == f"#{created['id']}"


async def test_sync_keeps_cursor_on_the_synced_row(tmp_path):
    todo_store, task_store = _store_pair(tmp_path)
    todo = todo_store.add(subject="Fix the widget", description="", parent_id=None)
    todo_store.set_redmine_issue(todo.id, 42)
    for days_ago in range(3):
        task_store.add(
            todo_id=todo.id,
            spent_on=date.today() - timedelta(days=days_ago),
            hours=1.0,
            activity=GENERAL_ACTIVITY,
            comments="",
        )
    ds = FakeDataSource()
    app = HarnessApp(ds, todo_store, task_store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("down", "down")
        await pilot.press("r")
        await pilot.pause()
        assert app.query_one("#entries", DataTable).cursor_row == 2


async def test_sync_logs_under_the_issues_own_project(tmp_path):
    # Regression: sync always sent the first project (Brickz) as project_id, and
    # Redmine rejected issues from any other project as "Issue is invalid".
    todo_store, task_store = _store_pair(tmp_path)
    todo = todo_store.add(subject="Fix the widget", description="", parent_id=None)
    todo_store.set_redmine_issue(todo.id, 32618)
    task_store.add(
        todo_id=todo.id, spent_on=date.today(), hours=1.0, activity=GENERAL_ACTIVITY, comments=""
    )
    ds = FakeDataSource(issue_projects={32618: 110})
    app = HarnessApp(ds, todo_store, task_store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("r")
        await pilot.pause()

    assert ds.created[0]["project_id"] == 110


async def test_sync_key_updates_already_linked_entry(tmp_path):
    todo_store, task_store = _store_pair(tmp_path)
    todo = todo_store.add(subject="Fix the widget", description="", parent_id=None)
    todo_store.set_redmine_issue(todo.id, 42)
    entry = task_store.add(
        todo_id=todo.id,
        spent_on=date.today(),
        hours=1.0,
        activity=GENERAL_ACTIVITY,
        comments="",
        redmine_entry_id=777,
    )
    ds = FakeDataSource()
    app = HarnessApp(ds, todo_store, task_store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("r")
        await pilot.pause()

    assert ds.created == []
    assert [u["entry_id"] for u in ds.updated] == [777]
    assert task_store.get(entry.id).redmine_entry_id == 777


async def test_sync_key_without_issue_does_nothing(tmp_path):
    todo_store, task_store = _store_pair(tmp_path)
    todo = todo_store.add(subject="Fix the widget", description="", parent_id=None)
    entry = task_store.add(
        todo_id=todo.id, spent_on=date.today(), hours=1.0, activity=GENERAL_ACTIVITY, comments=""
    )
    ds = FakeDataSource()
    app = HarnessApp(ds, todo_store, task_store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("r")
        await pilot.pause()

    assert ds.created == [] and ds.updated == []
    assert task_store.get(entry.id).redmine_entry_id is None


async def test_sync_failure_leaves_entry_unlinked(tmp_path):
    todo_store, task_store = _store_pair(tmp_path)
    todo = todo_store.add(subject="Fix the widget", description="", parent_id=None)
    todo_store.set_redmine_issue(todo.id, 42)
    entry = task_store.add(
        todo_id=todo.id, spent_on=date.today(), hours=1.0, activity=GENERAL_ACTIVITY, comments=""
    )
    ds = FakeDataSource()

    def fail(**_):
        raise RuntimeError("boom")

    ds.create_time_entry = fail
    app = HarnessApp(ds, todo_store, task_store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("r")
        await pilot.pause()

    assert task_store.get(entry.id).redmine_entry_id is None


async def test_row_shows_task_issue_and_redmine_link(tmp_path):
    todo_store, task_store = _store_pair(tmp_path)
    parent = todo_store.add(subject="Project", description="", parent_id=None)
    todo_store.set_redmine_issue(parent.id, 42)
    todo = todo_store.add(subject="Fix the widget", description="", parent_id=parent.id)
    task_store.add(
        todo_id=todo.id,
        spent_on=date.today(),
        hours=1.5,
        activity="Development",
        comments="notes",
        redmine_entry_id=777,
    )
    app = HarnessApp(FakeDataSource(), todo_store, task_store, owner_name="Hogyai Attila")
    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one("#entries", DataTable)
        assert table.row_count == 1
        row = [str(c) for c in table.get_row_at(0)]
        assert row == [
            date.today().isoformat(),
            "Hogyai Attila",
            "Development",
            "Project › Fix the widget",
            "#42",
            "notes",
            "1.5",
            "#777",
        ]


async def test_entries_sorted_newest_first(tmp_path):
    todo_store, task_store = _store_pair(tmp_path)
    todo = todo_store.add(subject="Fix the widget", description="", parent_id=None)
    for days_ago in (3, 0, 1):
        task_store.add(
            todo_id=todo.id,
            spent_on=date.today() - timedelta(days=days_ago),
            hours=1.0,
            activity=GENERAL_ACTIVITY,
            comments="",
        )
    app = HarnessApp(FakeDataSource(), todo_store, task_store)
    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one("#entries", DataTable)
        dates = [str(table.get_row_at(i)[0]) for i in range(table.row_count)]
        assert dates == sorted(dates, reverse=True)


async def test_issue_filter_uses_effective_issue(tmp_path):
    todo_store, task_store = _store_pair(tmp_path)
    parent = todo_store.add(subject="Project", description="", parent_id=None)
    todo_store.set_redmine_issue(parent.id, 42)
    linked = todo_store.add(subject="Linked", description="", parent_id=parent.id)
    local = todo_store.add(subject="Local", description="", parent_id=None)
    for todo in (linked, local):
        task_store.add(
            todo_id=todo.id, spent_on=date.today(), hours=1.0, activity=GENERAL_ACTIVITY, comments=""
        )
    app = HarnessApp(FakeDataSource(), todo_store, task_store)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one("#issue-filter", Select).value = 42
        await pilot.pause()
        table = app.query_one("#entries", DataTable)
        assert table.row_count == 1
        assert str(table.get_row_at(0)[3]) == "Project › Linked"


async def test_add_task_entry_warns_when_no_leaf_todos(tmp_path):
    todo_store, task_store = _store_pair(tmp_path)
    app = HarnessApp(FakeDataSource(), todo_store, task_store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        assert isinstance(app.screen, TaskEntriesScreen)


async def test_delete_unlinked_entry_is_immediate(tmp_path):
    todo_store, task_store = _store_pair(tmp_path)
    todo = todo_store.add(subject="Fix the widget", description="", parent_id=None)
    task_store.add(
        todo_id=todo.id, spent_on=date.today(), hours=1.0, activity=GENERAL_ACTIVITY, comments=""
    )
    ds = FakeDataSource()
    app = HarnessApp(ds, todo_store, task_store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("d")
        await pilot.pause()

    assert task_store.all() == []
    assert ds.deleted == []


async def test_delete_linked_entry_confirms_and_deletes_redmine_entry(tmp_path):
    todo_store, task_store = _store_pair(tmp_path)
    todo = todo_store.add(subject="Fix the widget", description="", parent_id=None)
    task_store.add(
        todo_id=todo.id,
        spent_on=date.today(),
        hours=1.0,
        activity=GENERAL_ACTIVITY,
        comments="",
        redmine_entry_id=777,
    )
    ds = FakeDataSource()
    app = HarnessApp(ds, todo_store, task_store)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("d")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmScreen)
        await pilot.click("#confirm")
        await pilot.pause()

    assert task_store.all() == []
    assert ds.deleted == [777]


async def test_time_entries_tab_no_longer_shows_task_entries(tmp_path):
    todo_store, task_store = _store_pair(tmp_path)
    todo = todo_store.add(subject="Fix the widget", description="", parent_id=None)
    task_store.add(
        todo_id=todo.id, spent_on=date.today(), hours=1.0, activity=GENERAL_ACTIVITY, comments=""
    )
    real = TimeEntry(
        id=1,
        spent_on=date.today(),
        hours=2.0,
        project="Brickz",
        project_id=90,
        issue_id=None,
        issue_subject=None,
        user="Attila Hogyai",
        user_id=1,
        activity="Development",
        activity_id=1,
        comments="",
    )

    class TimeApp(App):
        def on_mount(self) -> None:
            self.push_screen(TimeEntriesScreen(FakeDataSource(entries=[real])))

    app = TimeApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one("#entries", DataTable).row_count == 1


def test_store_round_trips_redmine_fields(tmp_path):
    todo_store, task_store = _store_pair(tmp_path)
    todo = todo_store.add(subject="x", description="", parent_id=None)
    todo_store.set_redmine_issue(todo.id, 42)
    task_store.add(
        todo_id=todo.id,
        spent_on=date.today(),
        hours=1.0,
        activity=GENERAL_ACTIVITY,
        comments="",
        redmine_entry_id=777,
    )
    assert TodoStore(tmp_path / "todos.json").get(todo.id).redmine_issue_id == 42
    assert TaskEntryStore(tmp_path / "task_entries.json").all()[0].redmine_entry_id == 777
