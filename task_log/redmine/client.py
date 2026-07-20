from datetime import date

import requests

from task_log.config import RedmineConfig
from task_log.models import Activity, Project, TimeEntry

PAGE_LIMIT = 100


class RedmineApiError(RuntimeError):
    pass


class RedmineAuthError(RedmineApiError):
    pass


class RedmineUpdateError(RedmineApiError):
    pass


class RedmineClient:
    def __init__(self, cfg: RedmineConfig):
        self._cfg = cfg
        self._session = requests.Session()
        self._session.headers["X-Redmine-API-Key"] = cfg.api_key
        self._activities_cache: list[Activity] | None = None
        self._projects_cache: list[Project] | None = None
        self._current_user_id: int | None = None

    def list_time_entries(self) -> list[TimeEntry]:
        url = f"{self._cfg.base_url}/projects/{self._cfg.project_identifier}/time_entries.json"
        raw_entries = self._get_paginated(url, "time_entries")

        issue_ids = {e["issue"]["id"] for e in raw_entries if e.get("issue")}
        subjects = self._fetch_issue_subjects(issue_ids)

        return [self._to_time_entry(e, subjects) for e in raw_entries]

    def _to_time_entry(self, raw: dict, subjects: dict[int, str]) -> TimeEntry:
        issue = raw.get("issue")
        issue_id = issue["id"] if issue else None
        return TimeEntry(
            id=raw["id"],
            spent_on=date.fromisoformat(raw["spent_on"]),
            hours=float(raw["hours"]),
            project=raw["project"]["name"],
            project_id=raw["project"]["id"],
            issue_id=issue_id,
            issue_subject=subjects.get(issue_id) if issue_id else None,
            user=raw["user"]["name"],
            user_id=raw["user"]["id"],
            activity=raw["activity"]["name"],
            activity_id=raw["activity"]["id"],
            comments=raw.get("comments", ""),
        )

    def _fetch_issue_subjects(self, issue_ids: set[int]) -> dict[int, str]:
        subjects: dict[int, str] = {}
        ids = sorted(issue_ids)
        for i in range(0, len(ids), PAGE_LIMIT):
            batch = ids[i : i + PAGE_LIMIT]
            url = f"{self._cfg.base_url}/issues.json"
            params = {
                "issue_id": ",".join(str(i) for i in batch),
                "status_id": "*",
                "limit": PAGE_LIMIT,
            }
            resp = self._session.get(url, params=params, timeout=10)
            self._raise_for_auth(resp)
            resp.raise_for_status()
            for issue in resp.json()["issues"]:
                subjects[issue["id"]] = issue["subject"]
        return subjects

    def list_activities(self) -> list[Activity]:
        if self._activities_cache is None:
            url = f"{self._cfg.base_url}/enumerations/time_entry_activities.json"
            resp = self._session.get(url, timeout=10)
            self._raise_for_auth(resp)
            resp.raise_for_status()
            self._activities_cache = [
                Activity(id=a["id"], name=a["name"], is_default=a.get("is_default", False))
                for a in resp.json()["time_entry_activities"]
            ]
        return self._activities_cache

    def list_projects(self) -> list[Project]:
        if self._projects_cache is None:
            url = f"{self._cfg.base_url}/projects.json"
            raw_projects = self._get_paginated(url, "projects")
            self._projects_cache = [Project(id=p["id"], name=p["name"]) for p in raw_projects]
        return self._projects_cache

    def current_user_id(self) -> int:
        if self._current_user_id is None:
            url = f"{self._cfg.base_url}/users/current.json"
            resp = self._session.get(url, timeout=10)
            self._raise_for_auth(resp)
            resp.raise_for_status()
            self._current_user_id = resp.json()["user"]["id"]
        return self._current_user_id

    def update_time_entry(
        self,
        entry_id: int,
        *,
        project_id: int,
        spent_on: date,
        hours: float,
        issue_id: int | None,
        activity_id: int,
        comments: str,
    ) -> None:
        url = f"{self._cfg.base_url}/time_entries/{entry_id}.json"
        body = {
            "time_entry": {
                "project_id": project_id,
                "spent_on": spent_on.isoformat(),
                "hours": hours,
                "issue_id": issue_id,
                "activity_id": activity_id,
                "comments": comments,
            }
        }
        resp = self._session.put(url, json=body, timeout=10)
        if resp.status_code == 404:
            raise RedmineUpdateError(f"Time entry {entry_id} no longer exists — refresh and retry")
        self._raise_for_write_errors(resp)

    def create_time_entry(
        self,
        *,
        project_id: int,
        spent_on: date,
        hours: float,
        issue_id: int | None,
        activity_id: int,
        comments: str,
    ) -> None:
        url = f"{self._cfg.base_url}/time_entries.json"
        body = {
            "time_entry": {
                "project_id": project_id,
                "spent_on": spent_on.isoformat(),
                "hours": hours,
                "issue_id": issue_id,
                "activity_id": activity_id,
                "comments": comments,
            }
        }
        resp = self._session.post(url, json=body, timeout=10)
        self._raise_for_write_errors(resp)

    @staticmethod
    def _raise_for_write_errors(resp: requests.Response) -> None:
        if resp.status_code in (401, 403):
            raise RedmineAuthError("Not authorized for this time entry")
        if resp.status_code == 422:
            errors = resp.json().get("errors", ["Validation failed"])
            raise RedmineUpdateError("; ".join(errors))
        resp.raise_for_status()

    def _get_paginated(self, url: str, key: str) -> list[dict]:
        results: list[dict] = []
        offset = 0
        while True:
            resp = self._session.get(url, params={"limit": PAGE_LIMIT, "offset": offset}, timeout=10)
            self._raise_for_auth(resp)
            resp.raise_for_status()
            data = resp.json()
            results.extend(data[key])
            offset += PAGE_LIMIT
            if offset >= data["total_count"]:
                break
        return results

    @staticmethod
    def _raise_for_auth(resp: requests.Response) -> None:
        if resp.status_code in (401, 403):
            raise RedmineAuthError(f"Redmine API authorization failed ({resp.status_code}) — check api_key in config.toml")
