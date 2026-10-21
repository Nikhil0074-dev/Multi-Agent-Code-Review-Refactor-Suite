from app.evaluation.metrics import CaseResult, ExpectedIssue, aggregate, match_case
from app.validation.schemas import ConsensusFinding, Finding
from tests.conftest import finding_json


def CF(path="app/users.py", start=12, end=12, title="Some finding title"):
    return ConsensusFinding.from_finding(Finding.model_validate({"agent": "security", **finding_json(
        file_path=path, start_line=start, end_line=end, title=title)}))


E = ExpectedIssue("app/users.py", 12, 12)


def test_true_positive_false_positive_duplicate():
    r = CaseResult("c", [E], [CF(), CF(title="Another title here"), CF(path="other.py")])
    c = match_case(r)
    assert (c.true_positives, c.duplicates, c.false_positives, c.exact_locations) == (1, 1, 1, 1)


def test_tolerance_and_exactness():
    near = CaseResult("c", [E], [CF(start=14, end=14)])
    c = match_case(near, tolerance=3)
    assert c.true_positives == 1 and c.exact_locations == 0
    assert match_case(near, tolerance=0).false_positives == 1


def test_aggregate_values():
    cases = [
        CaseResult("a", [E], [CF()], duration=2.0, llm_calls=4),
        CaseResult("b", [E], [], duration=4.0, llm_calls=2),
        CaseResult("clean", [], [CF(path="x.py")], duration=0.0),
        CaseResult("clean2", [], []),
    ]
    m = aggregate(cases)
    assert m["precision"] == 0.5 and m["recall"] == 0.5 and m["f1"] == 0.5
    assert m["false_positive_rate_clean"] == 0.5 and m["localization_accuracy"] == 1.0
    assert m["avg_latency_seconds"] == 1.5 and m["avg_llm_calls"] == 1.5


def test_empty_inputs_do_not_divide_by_zero():
    m = aggregate([])
    assert m["precision"] == 0.0 and m["f1"] == 0.0 and m["cases"] == 0.0
    assert aggregate([CaseResult("c", [], [])])["recall"] == 0.0
