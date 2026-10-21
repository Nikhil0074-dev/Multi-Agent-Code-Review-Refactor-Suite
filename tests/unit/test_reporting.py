from app.reporting.json_report import load_report, write_reports
from app.reporting.markdown_report import marker_for, render_inline_comment, render_markdown, sanitize
from app.validation.schemas import ConsensusFinding, ConsensusReport, Finding
from tests.conftest import finding_json


def CF(**over):
    agent = over.pop("agent", "security")
    return ConsensusFinding.from_finding(Finding.model_validate({"agent": agent, **finding_json(**over)}))


def test_report_contains_findings_marker_and_counts():
    report = ConsensusReport(head_sha="abc123", summary="1 finding(s): 1 high.", findings=[CF()])
    md = render_markdown(report)
    assert marker_for("abc123") in md and "[High] SQL injection" in md and "`app/users.py` · line 12" in md
    assert "| Critical | High |" in md and "Automated review" in md


def test_optional_findings_are_collapsed_and_errors_shown():
    f = CF()
    f.status = "optional"
    report = ConsensusReport(status="partial", summary="s", findings=[f], agent_errors={"security": "boom"},
                             skipped_files=["a.png (binary file)"])
    md = render_markdown(report)
    assert "<details><summary>Optional suggestions (1)" in md and "security: boom" in md and "not fully reviewed" in md


def test_no_findings_report():
    md = render_markdown(ConsensusReport(status="no_findings", summary="No actionable findings."))
    assert "No actionable findings." in md and "| Critical" not in md


def test_untrusted_text_is_neutralised():
    assert "@\u200bbob" in sanitize("ping @bob") and "<!--" not in sanitize("<!-- hide -->")
    f = CF(explanation="cc @admin <!-- x -->")
    assert "@admin" not in render_markdown(ConsensusReport(head_sha="s", findings=[f]))
    assert "@admin" not in render_inline_comment(f)


def test_patch_fence_survives_backticks_and_truncation():
    f = CF()
    f.suggested_patch = "```\ncode\n```"
    f.patch_status = "applies cleanly"
    md = render_markdown(ConsensusReport(findings=[f]))
    assert "````diff" in md and "Patch check" in md
    big = ConsensusReport(summary="x" * 70000)
    assert len(render_markdown(big)) < 61000 and "truncated" in render_markdown(big)


def test_json_roundtrip_and_bad_file(tmp_path):
    report = ConsensusReport(head_sha="h", findings=[CF()])
    jp, mp = write_reports(report, tmp_path / "out")
    assert load_report(jp) == report and mp.read_text().startswith("## AI Code Review")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    import pytest
    with pytest.raises(ValueError):
        load_report(bad)
