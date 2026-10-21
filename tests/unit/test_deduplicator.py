from app.debate.deduplicator import deduplicate, is_duplicate, title_similarity
from app.validation.schemas import Finding
from tests.conftest import finding_json


def F(agent="security", **over):
    return Finding.model_validate({"agent": agent, **finding_json(**over)})


def test_same_issue_from_two_agents_is_merged():
    a = F("security", title="SQL injection in email query", severity="high", confidence=0.9)
    b = F("clean_code", title="SQL injection through email query string", severity="low", confidence=0.6, start_line=13, end_line=13)
    out = deduplicate([a, b])
    assert len(out) == 1
    m = out[0]
    assert m.agents == ["clean_code", "security"] and m.severity == "high" and m.confidence == 0.9
    assert len(m.merged_ids) == 2 and any("Merged 2" in n for n in m.notes)


def test_different_problems_stay_separate():
    a = F("security", title="SQL injection in email query")
    b = F("performance", title="Repeated database lookups in loop", start_line=12)
    c = F("security", title="SQL injection in email query", start_line=80, end_line=80)
    assert len(deduplicate([a, b, c])) == 3
    assert not is_duplicate(a, F(file_path="app/orders.py"))


def test_transitive_merge_and_patch_kept():
    a = F(title="Unsafe SQL query construction", start_line=10, end_line=10)
    b = F("performance", title="Unsafe SQL query construction", start_line=12, end_line=12, suggested_patch="diff-b")
    c = F("clean_code", title="Unsafe SQL query construction", start_line=14, end_line=14)
    out = deduplicate([a, b, c])
    assert len(out) == 1 and out[0].suggested_patch == "diff-b"


def test_hypothesis_only_when_all_members_are():
    a = F("performance", title="Repeated lookups in loop", is_hypothesis=True)
    b = F("clean_code", title="Repeated lookups in loop", is_hypothesis=False)
    assert deduplicate([a, b])[0].is_hypothesis is False
    assert deduplicate([a])[0].is_hypothesis is True


def test_empty_and_similarity_bounds():
    assert deduplicate([]) == []
    assert title_similarity("abc", "abc") == 1.0 and title_similarity("sql injection", "memory leak") < 0.5
