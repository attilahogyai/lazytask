import csv
import io
import re
from datetime import date

import requests

from task_log.config import RedmineConfig
from task_log.models import TimeEntry

CSV_ENCODING = "cp1250"
ISSUE_RE = re.compile(r"#(\d+):\s*(.*)$")


class RedmineLoginError(RuntimeError):
    pass


class RedmineClient:
    def __init__(self, cfg: RedmineConfig):
        self._cfg = cfg
        self._session = requests.Session()
        self._logged_in = False

    def _ensure_login(self) -> None:
        if self._logged_in:
            return
        login_url = f"{self._cfg.base_url}/login"
        resp = self._session.get(login_url, timeout=10)
        resp.raise_for_status()
        token = self._scrape_csrf_token(resp.text)
        payload = {
            "authenticity_token": token,
            "back_url": login_url,
            "username": self._cfg.username,
            "password": self._cfg.password,
            "login": "Login",
        }
        resp = self._session.post(login_url, data=payload, timeout=10, allow_redirects=True)
        resp.raise_for_status()
        if "/login" in resp.url or "login-form" in resp.text.lower()[:3000]:
            raise RedmineLoginError("Login failed: check username/password")
        self._logged_in = True

    @staticmethod
    def _scrape_csrf_token(html: str) -> str:
        m = re.search(r'name="authenticity_token"\s+value="([^"]+)"', html)
        if not m:
            raise RedmineLoginError("Could not find CSRF token on login page")
        return m.group(1)

    def list_time_entries(self) -> list[TimeEntry]:
        self._ensure_login()
        url = f"{self._cfg.base_url}/projects/{self._cfg.project_identifier}/time_entries.csv"
        resp = self._session.get(url, timeout=10)
        resp.raise_for_status()
        text = resp.content.decode(CSV_ENCODING)
        return self._parse_csv(text)

    def _parse_csv(self, text: str) -> list[TimeEntry]:
        entries = []
        for row in csv.DictReader(io.StringIO(text)):
            issue_id, issue_subject = self._parse_issue(row.get("Issue", ""))
            entries.append(TimeEntry(
                id=len(entries),
                spent_on=date.fromisoformat(row["Date"]),
                hours=float(row["Hours"]),
                project=self._cfg.project_identifier,
                issue_id=issue_id,
                issue_subject=issue_subject,
                user=row["User"],
                activity=row["Activity"],
                comments=row.get("Comment", ""),
            ))
        return entries

    @staticmethod
    def _parse_issue(raw: str) -> tuple[int | None, str | None]:
        m = ISSUE_RE.search(raw)
        if not m:
            return None, None
        return int(m.group(1)), m.group(2)
