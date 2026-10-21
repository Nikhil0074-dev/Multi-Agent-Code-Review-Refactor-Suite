import json

from app.agents import CleanCodeMentor, PerformanceSpecialist, SecurityAnalyst
from app.debate.peer_challenge import run_peer_challenge, select_for_challenge
from app.llm.provider import LLMError, MockLLMClient
from app.validation.schemas import ConsensusFinding, Finding
from tests.conftest import finding_json


def CF(**over):
    return ConsensusFinding.from_finding(Finding.model_validate({"agent": "security", **finding_json(**over)}))


def test_selection_orders_by_severity_and_caps():
    a, b, c = CF(severity="low", title="low one here"), CF(severity="high"), CF(severity="medium", title="medium one")
    assert select_for_challenge([a, b, c], 2) == [b, c] and select_for_challenge([a], 0) == []


def test_only_other_agents_challenge_and_votes_are_collected(sample_files):
    f = CF()
    seen = []

    def handler(system, user):
        seen.append(system.split("\n")[0])
        return json.dumps({"challenges": [{"target_id": f.id, "verdict": "agree", "reason": "ok"}]})

    llm = MockLLMClient(handler=handler)
    agents = [SecurityAnalyst(llm), PerformanceSpecialist(llm), CleanCodeMentor(llm)]
    result, errors = run_peer_challenge(agents, sample_files, [f], max_challenged=5, max_chars=50000)
    assert errors == {} and len(result[f.id]) == 2
    assert {c.challenger for c in result[f.id]} == {"performance", "clean_code"}
    assert not any("Security Analyst" in s for s in seen)


def test_failed_challenger_is_reported_not_fatal(sample_files):
    f = CF()

    def handler(system, user):
        raise LLMError("down")

    llm = MockLLMClient(handler=handler)
    agents = [SecurityAnalyst(llm), CleanCodeMentor(llm)]
    result, errors = run_peer_challenge(agents, sample_files, [f], max_challenged=5, max_chars=50000)
    assert result == {} and "clean_code" in errors


def test_nothing_to_do_makes_no_calls(sample_files):
    llm = MockLLMClient()
    one = [SecurityAnalyst(llm)]
    assert run_peer_challenge(one, sample_files, [CF()], max_challenged=5, max_chars=50000) == ({}, {})
    two = [SecurityAnalyst(llm), CleanCodeMentor(llm)]
    assert run_peer_challenge(two, sample_files, [], max_challenged=5, max_chars=50000) == ({}, {})
    assert run_peer_challenge(two, sample_files, [CF()], max_challenged=0, max_chars=50000) == ({}, {})
    assert llm.calls == []
