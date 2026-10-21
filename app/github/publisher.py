"""Publish a report to a pull request without ever losing it."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.github.client import GitHubClient, GitHubError
from app.github.diff_parser import parse_diff
from app.github.pull_request import load_pull_request
from app.reporting.markdown_report import marker_for, render_inline_comment, render_markdown
from app.validation.line_mapper import map_to_inline
from app.validation.schemas import ConsensusReport

log = logging.getLogger(__name__)
MAX_INLINE = 25


@dataclass
class PublishResult:
    status: str  # published, already_published, stale, failed
    inline_posted: int = 0
    moved_to_summary: int = 0
    detail: str = ""
    errors: list[str] = field(default_factory=list)


def publish_report(
    client: GitHubClient,
    pr_number: int,
    report: ConsensusReport,
    *,
    inline: bool = False,
) -> PublishResult:
    if report.status == "failed":
        return PublishResult("failed", detail="report status is failed; nothing published")
    if not report.head_sha:
        return PublishResult("failed", detail="report has no head_sha")

    pr = load_pull_request(client, pr_number)
    if pr.head_sha != report.head_sha:
        return PublishResult("stale", detail=f"PR head is {pr.head_sha[:7]}, report is for {report.head_sha[:7]}")

    marker = marker_for(report.head_sha)
    try:
        for review in client.list_reviews(pr_number):
            if marker in (review.get("body") or ""):
                return PublishResult("already_published", detail="a review for this commit already exists")
    except GitHubError as exc:
        log.warning("could not list existing reviews: %s", exc)

    comments: list[dict] = []
    if inline:
        try:
            files = parse_diff(client.get_pull_diff(pr_number))
        except GitHubError as exc:
            files = {}
            log.warning("could not fetch diff for inline mapping: %s", exc)
        for f in report.findings:
            if f.status == "optional" or len(comments) >= MAX_INLINE:
                continue
            pos = map_to_inline(f.file_path, f.start_line, f.end_line, files)
            if pos is not None:
                comments.append(pos.to_api(render_inline_comment(f)))

    # The summary always holds the full report, so nothing depends on inline comments.
    errors: list[str] = []
    body = render_markdown(report)
    try:
        client.create_review(pr_number, report.head_sha, body, comments or None)
        return PublishResult("published", len(comments), 0, errors=errors)
    except GitHubError as exc:
        errors.append(f"review with inline comments rejected: {exc}")
        log.warning(errors[-1])

    # Fall back: whole report in the summary, no inline comments
    full_body = body
    try:
        client.create_review(pr_number, report.head_sha, full_body, None)
        return PublishResult("published", 0, len(comments), "inline comments were rejected; posted as summary", errors)
    except GitHubError as exc:
        errors.append(f"summary review rejected: {exc}")
    try:
        client.create_issue_comment(pr_number, full_body)
        return PublishResult("published", 0, len(comments), "posted as a plain PR comment", errors)
    except GitHubError as exc:
        errors.append(f"issue comment rejected: {exc}")
    return PublishResult("failed", detail="could not publish report", errors=errors)
