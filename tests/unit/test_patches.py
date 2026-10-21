import sys

import pytest

from app.config import Config
from app.github.diff_parser import parse_diff
from app.llm.provider import MockLLMClient
from app.refactor.patch_generator import PatchGenerator, build_patch, suggest_patches
from app.refactor.patch_validator import PatchError, apply_file_patch, run_checks, validate_patch
from app.validation.schemas import ConsensusFinding, ConsensusReport, Finding
from tests.conftest import finding_json

ORIGINAL = "def f(x):\n    q = f\"SELECT {x}\"\n    return q\n\n\ndef g():\n    return 1\n"


def CF(**over):
    args = {"file_path": "src/mod.py", "start_line": 2, "end_line": 2, **over}
    return ConsensusFinding.from_finding(Finding.model_validate({"agent": "security", **finding_json(**args)}))


def test_build_patch_and_apply_roundtrip():
    patch = build_patch("src/mod.py", ORIGINAL, 2, 2, '    q = ("SELECT ?", (x,))')
    assert patch.startswith("--- a/src/mod.py\n+++ b/src/mod.py")
    res = validate_patch(patch, {"src/mod.py": ORIGINAL}, {"src/mod.py"})
    assert res.valid and (res.added, res.removed) == (1, 1)
    assert res.new_contents["src/mod.py"].splitlines()[1] == '    q = ("SELECT ?", (x,))'


def test_build_patch_edge_cases():
    assert build_patch("p.py", ORIGINAL, 2, 2, '    q = f"SELECT {x}"\n') is None
    with pytest.raises(PatchError):
        build_patch("p.py", ORIGINAL, 5, 99, "x")
    deletion = build_patch("p.py", ORIGINAL, 7, 7, "")
    assert "-    return 1" in deletion
    multi = build_patch("p.py", ORIGINAL, 2, 3, "    return 0\n    # done")
    res = validate_patch(multi, {"p.py": ORIGINAL})
    assert res.valid and res.new_contents["p.py"].endswith("    return 1\n") and "# done" in res.new_contents["p.py"]


def test_pure_insertion_applies():
    patch = build_patch("p.py", ORIGINAL, 1, 1, "# header\ndef f(x):")
    assert validate_patch(patch, {"p.py": ORIGINAL}).new_contents["p.py"].startswith("# header\ndef f(x):\n")


@pytest.mark.parametrize("patch,why", [
    ("", "empty"),
    ("just text", "no file changes"),
    ("--- a/x.py\n+++ b/../evil.py\n@@ -1 +1 @@\n-a\n+b\n", "unsafe path"),
    ("--- a/other.py\n+++ b/other.py\n@@ -1 +1 @@\n-a\n+b\n", "outside the allowed"),
    ("--- /dev/null\n+++ b/src/mod.py\n@@ -0,0 +1 @@\n+a\n", "in-place"),
    ("--- a/src/mod.py\n+++ b/src/mod.py\n@@ -1 +1 @@\n-WRONG\n+b\n", "context mismatch"),
])
def test_invalid_patches_are_rejected(patch, why):
    res = validate_patch(patch, {"src/mod.py": ORIGINAL}, {"src/mod.py"})
    assert not res.valid and why in " ".join(res.errors) and res.new_contents == {}


def test_size_limit_and_missing_original():
    patch = build_patch("src/mod.py", ORIGINAL, 1, 7, "\n".join(f"l{i}" for i in range(300)))
    assert "more than" in " ".join(validate_patch(patch, {"src/mod.py": ORIGINAL}, max_changed_lines=50).errors)
    assert "not available" in " ".join(validate_patch(patch, {}).errors)


def test_apply_file_patch_overlap_error():
    fd = parse_diff("--- a/f\n+++ b/f\n@@ -2 +2 @@\n-b\n+B\n@@ -1 +1 @@\n-a\n+A\n")["f"]
    with pytest.raises(PatchError):
        apply_file_patch("a\nb\n", fd)


def test_run_checks_uses_copy_and_reports_result(tmp_path):
    (tmp_path / "m.py").write_text("VALUE = 1\n")
    code = "import m, sys; sys.exit(0 if m.VALUE == 2 else 1)"
    ok, _ = run_checks(tmp_path, {"m.py": "VALUE = 2\n"}, [sys.executable, "-c", code])
    bad, out = run_checks(tmp_path, {"m.py": "VALUE = 3\n"}, [sys.executable, "-c", code])
    assert ok and not bad
    assert (tmp_path / "m.py").read_text() == "VALUE = 1\n"  # real repo untouched
    assert run_checks(tmp_path, {}, [sys.executable, "-c", "import time; time.sleep(5)"], timeout=1) == (False, "timed out after 1s")
    assert run_checks(tmp_path, {}, ["definitely-not-a-command-xyz"])[0] is False
    with pytest.raises(PatchError):
        run_checks(tmp_path, {"../x.py": "1"}, ["true"])
    with pytest.raises(PatchError):
        run_checks(tmp_path, {}, [])


def test_env_has_no_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "super-secret")
    code = "import os, sys; sys.exit(1 if 'LLM_API_KEY' in os.environ else 0)"
    assert run_checks(tmp_path, {}, [sys.executable, "-c", code])[0]


def test_generator_uses_model_replacement():
    llm = MockLLMClient(responses=['{"replacement": "    q = (x,)"}'])
    patch = PatchGenerator(llm).generate(CF(), ORIGINAL)
    assert "+    q = (x,)" in patch and "TASK: PATCH" in llm.calls[0][1]
    assert PatchGenerator(MockLLMClient(responses=['{"replacement": ""}'])).generate(CF(), ORIGINAL) is None
    with pytest.raises(PatchError):
        PatchGenerator(MockLLMClient(responses=["bad", "bad"]), max_retries=1).generate(CF(), ORIGINAL)
    with pytest.raises(PatchError):
        PatchGenerator(MockLLMClient()).generate(CF(start_line=50, end_line=50), ORIGINAL)


def test_suggest_patches_end_to_end(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "mod.py").write_text(ORIGINAL)
    cfg = Config(backend="mock", patch_test_command=f"{sys.executable} -c 'import sys; sys.exit(0)'")
    ok = CF()
    skipped_low = CF(severity="low", title="Low severity thing")
    missing = ConsensusFinding.from_finding(Finding.model_validate({"agent": "security", **finding_json(file_path="nope.py")}))
    report = ConsensusReport(findings=[ok, skipped_low, missing])
    llm = MockLLMClient(handler=lambda s, u: '{"replacement": "    q = (x,)"}')
    assert suggest_patches(report, tmp_path, llm, cfg) == 1
    assert "tests passed" in report.findings[0].patch_status and report.findings[0].suggested_patch
    assert report.findings[1].patch_status is None and "not found" in report.findings[2].patch_status
    assert (tmp_path / "src" / "mod.py").read_text() == ORIGINAL


def test_suggest_patches_parses_windows_test_command(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "mod.py").write_text(ORIGINAL)
    cfg = Config(backend="mock", patch_test_command=f'{sys.executable} -c "import sys; sys.exit(0)"')
    report = ConsensusReport(findings=[CF()])
    llm = MockLLMClient(handler=lambda s, u: '{"replacement": "    q = (x,)"}')

    assert suggest_patches(report, tmp_path, llm, cfg) == 1
    assert "tests passed" in report.findings[0].patch_status


def test_suggest_patches_rejects_when_tests_fail(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "mod.py").write_text(ORIGINAL)
    cfg = Config(backend="mock", patch_test_command=f"{sys.executable} -c 'import sys; sys.exit(1)'")
    report = ConsensusReport(findings=[CF()])
    llm = MockLLMClient(handler=lambda s, u: '{"replacement": "    q = (x,)"}')
    assert suggest_patches(report, tmp_path, llm, cfg) == 0
    assert report.findings[0].suggested_patch is None and "tests failed" in report.findings[0].patch_status
