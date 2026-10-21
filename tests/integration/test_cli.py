import json
import sys

from app import publish, review
from app.evaluation import run_eval
from app.github.client import GitHubClient
from app.llm.provider import MockLLMClient
from tests.conftest import FIXTURES, ROOT, analysis_reply, finding_json
from tests.unit.test_github import FakeGitHub


def sql_llm():
    return MockLLMClient(handler=lambda s, u: analysis_reply(finding_json()) if ("TASK: ANALYZE" in u and "Security Analyst" in s) else
                         ('{"challenges": []}' if "TASK: CHALLENGE" in u else analysis_reply()))


def test_review_cli_with_diff_file_writes_reports(tmp_path, capsys):
    out = tmp_path / "out"
    code = review.main(["--diff-file", str(FIXTURES / "sample_diff.patch"), "--out-dir", str(out), "--backend", "mock"],
                       llm=sql_llm(), env={"HEAD_SHA": "abc", "PR_NUMBER": "7"})
    assert code == 0
    data = json.loads((out / "report.json").read_text())
    assert data["status"] == "ok" and data["head_sha"] == "abc" and data["pr_number"] == 7
    assert data["findings"][0]["file_path"] == "app/users.py"
    assert "AI Code Review" in (out / "report.md").read_text()
    assert "Reports written" in capsys.readouterr().out


def test_review_cli_default_mock_is_clean_and_step_summary(tmp_path):
    summary = tmp_path / "summary.md"
    code = review.main(["--diff-file", str(FIXTURES / "sample_diff.patch"), "--out-dir", str(tmp_path / "o"), "--backend", "mock"],
                       env={"GITHUB_STEP_SUMMARY": str(summary)})
    assert code == 0 and "No actionable findings" in summary.read_text()


def test_review_cli_failures_return_codes(tmp_path, capsys):
    assert review.main(["--backend", "hosted"], env={}) == 2  # missing API key
    assert "LLM_API_KEY" in capsys.readouterr().err
    assert review.main(["--backend", "mock", "--diff-file", str(tmp_path / "missing.patch")], env={}) == 2
    assert review.main(["--backend", "mock"], env={}) == 2  # no diff source at all

    def broken(system, user):
        from app.llm.provider import LLMError
        raise LLMError("down")

    code = review.main(["--diff-file", str(FIXTURES / "sample_diff.patch"), "--out-dir", str(tmp_path / "f"), "--backend", "mock"],
                       llm=MockLLMClient(handler=broken), env={})
    assert code == 1 and json.loads((tmp_path / "f" / "report.json").read_text())["status"] == "failed"


def test_review_cli_skips_fork_prs(monkeypatch, capsys):
    class ForkGH(FakeGitHub):
        def __call__(self, req, timeout=None):
            resp = super().__call__(req, timeout)
            if req.get_method() == "GET" and req.full_url.endswith("/pulls/7") and "diff" not in req.get_header("Accept"):
                data = json.loads(resp.read())
                data["head"]["repo"]["full_name"] = "fork/r"
                from tests.unit.test_http_and_llm import FakeResp
                return FakeResp(json.dumps(data).encode())
            return resp

    fake = ForkGH()
    monkeypatch.setattr("app.review.GitHubClient", lambda *a, **k: GitHubClient(a[0], a[1], urlopen=fake, retries=0))
    env = {"GITHUB_TOKEN": "t", "GITHUB_REPOSITORY": "o/r", "PR_NUMBER": "7", "LLM_BACKEND": "mock"}
    assert review.main([], env=env) == 0 and "fork" in capsys.readouterr().out


def test_review_cli_fetches_diff_from_github(tmp_path, monkeypatch, sample_diff):
    fake = FakeGitHub(head="abc", diff=sample_diff)
    monkeypatch.setattr("app.review.GitHubClient", lambda *a, **k: GitHubClient(a[0], a[1], urlopen=fake, retries=0))
    env = {"GITHUB_TOKEN": "t", "GITHUB_REPOSITORY": "o/r", "PR_NUMBER": "7", "LLM_BACKEND": "mock", "REPORT_DIR": str(tmp_path)}
    assert review.main([], llm=sql_llm(), env=env) == 0
    data = json.loads((tmp_path / "report.json").read_text())
    assert data["head_sha"] == "abc" and data["base_sha"] == "base" and len(data["findings"]) == 1


def test_review_to_publish_roundtrip(tmp_path, sample_diff):
    review.main(["--diff-file", str(FIXTURES / "sample_diff.patch"), "--out-dir", str(tmp_path), "--backend", "mock"],
                llm=sql_llm(), env={"HEAD_SHA": "abc", "PR_NUMBER": "7"})
    fake = FakeGitHub(head="abc", diff=sample_diff)
    client = GitHubClient("t", "o/r", urlopen=fake, retries=0)
    env = {"REPORT_PATH": str(tmp_path / "report.json"), "ENABLE_INLINE_COMMENTS": "true"}
    assert publish.main(env, client=client) == 0
    body = fake.posted[0][1]
    assert body["commit_id"] == "abc" and body["comments"][0]["line"] == 12


def test_publish_cli_errors(tmp_path, capsys):
    assert publish.main({}) == 2
    assert publish.main({"REPORT_PATH": str(tmp_path / "nope.json")}) == 2
    bad = tmp_path / "r.json"
    bad.write_text("{}")
    assert publish.main({"REPORT_PATH": str(bad)}) == 2  # no PR number, no sha
    assert "PR_NUMBER" in capsys.readouterr().err


def test_eval_runner_compares_three_modes(tmp_path, capsys):
    def handler(system, user):
        if "TASK: CHALLENGE" in user:
            return '{"challenges": []}'
        if "app/users.py" in user:
            return analysis_reply(finding_json())
        return analysis_reply()

    out = tmp_path / "res.json"
    code = run_eval.main(["--cases", str(ROOT / "evaluation" / "cases"), "--out", str(out), "--backend", "mock"], llm=MockLLMClient(handler=handler))
    assert code == 0
    res = json.loads(out.read_text())
    assert set(res) == {"single", "independent", "debate"}
    assert res["debate"]["recall"] == 0.5 and res["debate"]["false_positive_rate_clean"] == 0.0
    assert "C three agents + debate" in capsys.readouterr().out


def test_eval_runner_bad_cases_dir(tmp_path, capsys):
    assert run_eval.main(["--cases", str(tmp_path), "--backend", "mock"]) == 2
    assert "no case files" in capsys.readouterr().err
    (tmp_path / "x.json").write_text('{"id": "x"}')
    assert run_eval.main(["--cases", str(tmp_path), "--backend", "mock"]) == 2


def test_python_module_entry_points_run():
    import subprocess
    proc = subprocess.run([sys.executable, "-m", "app.review", "--diff-file", str(FIXTURES / "sample_diff.patch"),
                           "--backend", "mock", "--out-dir", "/tmp/mar-cli-test"], cwd=ROOT, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "no_findings" in proc.stdout


def _git(cwd, *args):
    import subprocess
    return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=cwd,
                          capture_output=True, text=True, check=True).stdout.strip()


def test_review_cli_uses_local_git_diff_and_attaches_patch(tmp_path, monkeypatch):
    import shutil
    if not shutil.which("git"):
        import pytest
        pytest.skip("git not installed")
    repo = tmp_path / "repo"
    (repo / "app").mkdir(parents=True)
    _git(repo, "init", "-q")
    (repo / "app" / "users.py").write_text("import sqlite3\n\n\ndef find(conn, email):\n    cur = conn.cursor()\n    return cur\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "app" / "users.py").write_text(
        "import sqlite3\n\n\ndef find(conn, email):\n    cur = conn.cursor()\n"
        "    query = f\"SELECT * FROM users WHERE email = '{email}'\"\n    cur.execute(query)\n    return cur\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "change")
    head = _git(repo, "rev-parse", "HEAD")
    monkeypatch.chdir(repo)

    finding = finding_json(start_line=6, end_line=6)

    def handler(system, user):
        if "TASK: PATCH" in user:
            return json.dumps({"replacement": "    query = 'SELECT * FROM users WHERE email = ?'"})
        if "TASK: CHALLENGE" in user:
            return '{"challenges": []}'
        return analysis_reply(finding) if "Security Analyst" in system else analysis_reply()

    env = {"LLM_BACKEND": "mock", "BASE_SHA": base, "HEAD_SHA": head, "REPORT_DIR": str(tmp_path / "out"),
           "ENABLE_PATCHES": "true"}
    assert review.main([], llm=MockLLMClient(handler=handler), env=env) == 0
    data = json.loads((tmp_path / "out" / "report.json").read_text())
    f = data["findings"][0]
    assert f["start_line"] == 6 and "applies cleanly" in f["patch_status"] and "+    query = 'SELECT" in f["suggested_patch"]
    assert "f\"SELECT" in (repo / "app" / "users.py").read_text()  # repo untouched


def test_review_cli_git_diff_errors(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)  # not a git repo
    assert review.main([], env={"LLM_BACKEND": "mock", "BASE_SHA": "a", "HEAD_SHA": "b"}) == 2
    assert "Could not get the diff" in capsys.readouterr().err
