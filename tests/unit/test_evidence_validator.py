from app.github.diff_parser import parse_diff
from app.validation.evidence_validator import resolve_path, validate_finding, validate_findings
from app.validation.schemas import Finding
from tests.conftest import finding_json
from tests.helpers import make_diff


def make(**over):
    return Finding.model_validate({"agent": "security", **finding_json(**over)})


def test_valid_finding_passes(sample_files):
    r = validate_finding(make(), sample_files)
    assert r.valid and r.finding.start_line == 12


def test_unknown_file_binary_deleted(sample_files):
    assert "not part" in validate_finding(make(file_path="nope.py"), sample_files).reason
    files = parse_diff("diff --git a/i.png b/i.png\nBinary files a/i.png and b/i.png differ\n")
    assert not validate_finding(make(file_path="i.png"), files).valid
    gone = parse_diff("diff --git a/d.py b/d.py\ndeleted file mode 100644\n--- a/d.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-x\n")
    assert "deleted" in validate_finding(make(file_path="d.py"), gone).reason


def test_path_prefixes_are_resolved(sample_files):
    assert resolve_path("b/app/users.py", sample_files) == "app/users.py"
    assert validate_finding(make(file_path="./app/users.py"), sample_files).finding.file_path == "app/users.py"


def test_hallucinated_evidence_is_rejected(sample_files):
    r = validate_finding(make(evidence="os.system(user_input)"), sample_files)
    assert not r.valid and "does not appear" in r.reason


def test_wrong_lines_are_relocated_when_evidence_is_nearby(sample_files):
    r = validate_finding(make(start_line=14, end_line=14), sample_files)
    assert r.valid and (r.finding.start_line, r.finding.end_line) == (12, 12)


def test_evidence_far_away_is_rejected():
    old = "".join(f"x{i} = {i}\n" for i in range(60))
    new = old + "danger = eval(user)\n"
    files = parse_diff(make_diff("f.py", old, new, n=1))
    far = Finding.model_validate({"agent": "security", **finding_json(
        file_path="f.py", start_line=61, end_line=61, evidence="danger = eval(user)")})
    assert validate_finding(far, files).valid
    wrong = far.model_copy(update={"start_line": 1, "end_line": 1})
    assert not validate_finding(wrong, files).valid


def test_unchanged_context_only_is_rejected():
    old = "keep_a = 1\nkeep_b = 2\nkeep_c = 3\nkeep_d = 4\nkeep_e = 5\nkeep_f = 6\nkeep_g = 7\n"
    new = old.replace("keep_g = 7", "keep_g = 8")
    files = parse_diff(make_diff("f.py", old, new, n=3))
    f = Finding.model_validate({"agent": "security", **finding_json(
        file_path="f.py", start_line=5, end_line=5, evidence="keep_e = 5")})
    r = validate_finding(f, files)
    assert not r.valid and "do not touch changed code" in r.reason


def test_evidence_with_diff_markers_and_line_numbers_matches(sample_files):
    ev = "   12 +     query = f\"SELECT * FROM users WHERE email = '{email}'\""
    assert validate_finding(make(evidence=ev), sample_files).valid
    assert not validate_finding(make(evidence="x\n\n  "), sample_files).valid


def test_span_limit(sample_files):
    assert "longer" in validate_finding(make(start_line=1, end_line=500), sample_files).reason


def test_validate_findings_splits(sample_files):
    good, bad = validate_findings([make(), make(evidence="nothing like it here")], sample_files)
    assert len(good) == 1 and len(bad) == 1 and bad[0][1]
