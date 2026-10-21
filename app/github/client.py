"""Minimal GitHub REST client (standard library only)."""
from __future__ import annotations

import json
import re
from typing import Callable, Optional

from app.http_util import HTTPFailure, request


class GitHubError(RuntimeError):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


class GitHubClient:
    def __init__(
        self,
        token: str,
        repository: str,
        api_url: str = "https://api.github.com",
        timeout: int = 30,
        retries: int = 2,
        urlopen: Optional[Callable] = None,
    ) -> None:
        if not token:
            raise GitHubError("GitHub token is required")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository or ""):
            raise GitHubError(f"repository must look like 'owner/name', got {repository!r}")
        self.token = token
        self.repository = repository
        self.api_url = api_url.rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self._urlopen = urlopen

    def _call(self, method: str, path: str, *, body: Optional[dict] = None, accept: str = "application/vnd.github+json") -> bytes:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": accept,
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "multi-agent-code-review",
        }
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        try:
            _, _, payload = request(
                method,
                f"{self.api_url}/repos/{self.repository}{path}",
                headers=headers,
                data=data,
                timeout=self.timeout,
                urlopen=self._urlopen,
                retries=self.retries,
            )
        except HTTPFailure as exc:
            raise GitHubError(f"GitHub API error: {exc}", exc.status) from exc
        return payload

    def _json(self, method: str, path: str, body: Optional[dict] = None):
        raw = self._call(method, path, body=body)
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise GitHubError("GitHub returned invalid JSON") from exc

    def get_pull(self, number: int) -> dict:
        return self._json("GET", f"/pulls/{int(number)}")

    def get_pull_diff(self, number: int) -> str:
        raw = self._call("GET", f"/pulls/{int(number)}", accept="application/vnd.github.v3.diff")
        return raw.decode("utf-8", "replace")

    def list_reviews(self, number: int) -> list[dict]:
        data = self._json("GET", f"/pulls/{int(number)}/reviews?per_page=100")
        return data if isinstance(data, list) else []

    def create_review(self, number: int, commit_id: str, body: str, comments: Optional[list[dict]] = None) -> dict:
        payload: dict = {"commit_id": commit_id, "body": body, "event": "COMMENT"}
        if comments:
            payload["comments"] = comments
        return self._json("POST", f"/pulls/{int(number)}/reviews", payload)

    def create_issue_comment(self, number: int, body: str) -> dict:
        return self._json("POST", f"/issues/{int(number)}/comments", {"body": body})
