"""Pull request metadata."""
from __future__ import annotations

from dataclasses import dataclass

from app.github.client import GitHubClient, GitHubError


@dataclass(frozen=True)
class PullRequestInfo:
    number: int
    title: str
    state: str
    head_sha: str
    base_sha: str
    head_repo: str
    base_repo: str

    @property
    def is_fork(self) -> bool:
        return self.head_repo != self.base_repo


def parse_pull(data: dict) -> PullRequestInfo:
    try:
        head, base = data["head"], data["base"]
        head_repo = (head.get("repo") or {}).get("full_name", "")  # repo is null if fork was deleted
        return PullRequestInfo(
            number=int(data["number"]),
            title=str(data.get("title", "")),
            state=str(data.get("state", "")),
            head_sha=str(head["sha"]),
            base_sha=str(base["sha"]),
            head_repo=head_repo,
            base_repo=str((base.get("repo") or {}).get("full_name", "")),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise GitHubError(f"unexpected pull request payload: {exc}") from exc


def load_pull_request(client: GitHubClient, number: int) -> PullRequestInfo:
    return parse_pull(client.get_pull(number))
