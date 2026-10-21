import json

import pytest

from app.github.client import GitHubClient, GitHubError
from app.github.publisher import publish_report
from app.github.pull_request import load_pull_request, parse_pull
from app.reporting.markdown_report import marker_for
from app.validation.schemas import ConsensusFinding, ConsensusReport, Finding
from tests.conftest import finding_json
from tests.unit.test_http_and_llm import FakeResp, http_error


class FakeGitHub:
    """Routes requests by (method, path suffix) and records them."""

    def __init__(self, head="abc", reviews=None, fail_review_with_comments=False, fail_all_reviews=False, diff=""):
        self.head, self.reviews, self.diff = head, reviews or [], diff
        self.fail_comments, self.fail_all = fail_review_with_comments, fail_all_reviews
        self.posted = []

    def __call__(self, req, timeout=None):
        url, method = req.full_url, req.get_method()
        if method == "GET" and url.endswith("/pulls/7"):
            if "diff" in req.get_header("Accept"):
                return FakeResp(self.diff.encode())
            return FakeResp(json.dumps({"number": 7, "title": "t", "state": "open",
                                        "head": {"sha": self.head, "repo": {"full_name": "o/r"}},
                                        "base": {"sha": "base", "repo": {"full_name": "o/r"}}}).encode())
        if method == "GET" and "/reviews" in url:
            return FakeResp(json.dumps(self.reviews).encode())
        body = json.loads(req.data)
        if url.endswith("/reviews"):
            if self.fail_all or (self.fail_comments and body.get("comments")):
                raise http_error(422, b"bad line")
            self.posted.append(("review", body))
            return FakeResp(b"{}")
        if url.endswith("/comments"):
            self.posted.append(("comment", body))
            return FakeResp(b"{}")
        raise AssertionError(f"unexpected {method} {url}")


def gh(fake):
    return GitHubClient("tok", "o/r", urlopen=fake, retries=0)


def report(head="abc", status="ok"):
    f = ConsensusFinding.from_finding(Finding.model_validate({"agent": "security", **finding_json()}))
    return ConsensusReport(status=status, head_sha=head, summary="s", findings=[f], pr_number=7)


def test_client_validation_and_errors():
    with pytest.raises(GitHubError):
        GitHubClient("", "o/r")
    with pytest.raises(GitHubError):
        GitHubClient("t", "bad repo")
    op = lambda req, timeout=None: (_ for _ in ()).throw(http_error(404, b"nf"))  # noqa: E731
    with pytest.raises(GitHubError) as ei:
        GitHubClient("t", "o/r", urlopen=op, retries=0).get_pull(1)
    assert ei.value.status == 404


def test_pull_request_info():
    info = load_pull_request(gh(FakeGitHub()), 7)
    assert (info.head_sha, info.is_fork) == ("abc", False)
    forked = parse_pull({"number": 1, "head": {"sha": "h", "repo": {"full_name": "x/r"}}, "base": {"sha": "b", "repo": {"full_name": "o/r"}}})
    assert forked.is_fork
    deleted = parse_pull({"number": 1, "head": {"sha": "h", "repo": None}, "base": {"sha": "b", "repo": {"full_name": "o/r"}}})
    assert deleted.is_fork
    with pytest.raises(GitHubError):
        parse_pull({"number": 1})


def test_publish_summary_only():
    fake = FakeGitHub()
    res = publish_report(gh(fake), 7, report())
    assert res.status == "published" and res.inline_posted == 0
    kind, body = fake.posted[0]
    assert body["commit_id"] == "abc" and body["event"] == "COMMENT" and "comments" not in body
    assert marker_for("abc") in body["body"]


def test_stale_failed_and_duplicate_are_not_published():
    fake = FakeGitHub(head="newer")
    assert publish_report(gh(fake), 7, report()).status == "stale" and fake.posted == []
    assert publish_report(gh(FakeGitHub()), 7, report(status="failed")).status == "failed"
    assert publish_report(gh(FakeGitHub()), 7, report(head="")).status == "failed"
    dup = FakeGitHub(reviews=[{"body": "x " + marker_for("abc")}])
    assert publish_report(gh(dup), 7, report()).status == "already_published" and dup.posted == []


def test_inline_comments_use_valid_lines(sample_diff):
    fake = FakeGitHub(diff=sample_diff)
    res = publish_report(gh(fake), 7, report(), inline=True)
    comments = fake.posted[0][1]["comments"]
    assert res.inline_posted == 1 and comments[0]["line"] == 12 and comments[0]["path"] == "app/users.py"


def test_unmappable_finding_is_only_in_summary(sample_diff):
    r = report()
    r.findings[0].start_line = r.findings[0].end_line = 500
    fake = FakeGitHub(diff=sample_diff)
    res = publish_report(gh(fake), 7, r, inline=True)
    assert res.inline_posted == 0 and "comments" not in fake.posted[0][1] and "SQL injection" in fake.posted[0][1]["body"]


def test_rejected_inline_comments_fall_back_to_summary(sample_diff):
    fake = FakeGitHub(diff=sample_diff, fail_review_with_comments=True)
    res = publish_report(gh(fake), 7, report(), inline=True)
    assert res.status == "published" and res.moved_to_summary == 1 and res.errors
    assert "comments" not in fake.posted[0][1]


def test_total_review_failure_falls_back_to_issue_comment_then_fails():
    fake = FakeGitHub(fail_all_reviews=True)
    res = publish_report(gh(fake), 7, report())
    assert res.status == "published" and fake.posted[0][0] == "comment"

    class Broken(FakeGitHub):
        def __call__(self, req, timeout=None):
            if req.get_method() == "POST":
                raise http_error(403, b"forbidden")
            return super().__call__(req, timeout)

    res2 = publish_report(gh(Broken()), 7, report())
    assert res2.status == "failed" and len(res2.errors) == 3
