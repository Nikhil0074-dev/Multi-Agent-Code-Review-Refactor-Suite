import pytest
from pydantic import ValidationError

from app.validation.schemas import ConsensusFinding, ConsensusReport, Finding, is_safe_repo_path, normalize_repo_path
from tests.conftest import finding_json


def make(**over):
    return Finding.model_validate({"agent": "security", **finding_json(**over)})


def test_valid_finding_and_stable_id():
    f = make()
    assert f.finding_id == make().finding_id
    assert f.finding_id != make(start_line=13, end_line=13).finding_id


@pytest.mark.parametrize("over", [
    {"severity": "urgent"}, {"confidence": -0.1}, {"confidence": 120}, {"title": "abc"},
    {"evidence": ""}, {"start_line": 0}, {"start_line": 5, "end_line": 4},
    {"file_path": "../etc/passwd"}, {"file_path": "/abs/path"}, {"file_path": ""},
])
def test_invalid_findings_are_rejected(over):
    with pytest.raises(ValidationError):
        make(**over)


def test_lenient_normalisation():
    f = make(severity=" HIGH ", confidence=85, title="x" * 300, file_path="./app\\users.py")
    assert f.severity == "high" and f.confidence == 0.85 and len(f.title) == 160 and f.file_path == "app/users.py"


def test_path_helpers():
    assert normalize_repo_path("a//b/./c.py") == "a/b/c.py"
    assert not is_safe_repo_path("a/../b") and not is_safe_repo_path("C:\\x") and is_safe_repo_path("a/b.py")


def test_unknown_agent_rejected():
    with pytest.raises(ValidationError):
        Finding.model_validate({"agent": "bob", **finding_json()})


def test_consensus_roundtrip_and_counts():
    cf = ConsensusFinding.from_finding(make())
    report = ConsensusReport(findings=[cf])
    assert report.severity_counts()["high"] == 1
    again = ConsensusReport.model_validate_json(report.model_dump_json())
    assert again == report
