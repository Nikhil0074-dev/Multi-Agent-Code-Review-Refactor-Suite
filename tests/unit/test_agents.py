import pytest

from app.agents import AgentError, CleanCodeMentor, SecurityAnalyst
from app.context import ReviewContext
from app.llm.provider import LLMError, MockLLMClient
from app.validation.schemas import ConsensusFinding, Finding
from tests.conftest import analysis_reply, challenge_reply, finding_json


@pytest.fixture
def ctx(sample_files):
    return ReviewContext(files=list(sample_files.values()), head_sha="abc")


def test_analyze_parses_findings_and_forces_agent_name(ctx):
    llm = MockLLMClient(responses=[analysis_reply(finding_json(agent="performance"))])
    review = SecurityAnalyst(llm).analyze(ctx)
    assert len(review.findings) == 1 and review.findings[0].agent == "security"
    system, user = llm.calls[0]
    assert "Security Analyst" in system and "TASK: ANALYZE" in user and "app/users.py" in user


def test_invalid_findings_are_dropped_not_fatal(ctx):
    reply = analysis_reply(finding_json(), finding_json(severity="meh"), "junk", finding_json(start_line=0))
    review = SecurityAnalyst(MockLLMClient(responses=[reply])).analyze(ctx)
    assert len(review.findings) == 1 and len(review.rejected) == 3


def test_empty_findings_is_valid(ctx):
    review = CleanCodeMentor(MockLLMClient(responses=[analysis_reply()])).analyze(ctx)
    assert review.findings == [] and review.summary == "ok"


def test_retries_on_bad_json_then_succeeds(ctx):
    llm = MockLLMClient(responses=["not json at all", analysis_reply(finding_json())])
    review = SecurityAnalyst(llm, max_retries=1).analyze(ctx)
    assert len(review.findings) == 1 and len(llm.calls) == 2
    assert "rejected" in llm.calls[1][1]


def test_gives_up_after_retries(ctx):
    llm = MockLLMClient(responses=["bad", "worse", "still bad"])
    with pytest.raises(AgentError, match="no valid JSON"):
        SecurityAnalyst(llm, max_retries=2).analyze(ctx)
    assert len(llm.calls) == 3


def test_missing_findings_key_triggers_retry(ctx):
    llm = MockLLMClient(responses=['{"summary": "x"}', analysis_reply()])
    assert SecurityAnalyst(llm, max_retries=1).analyze(ctx).findings == []


def test_llm_error_is_wrapped_without_retry(ctx):
    def boom(system, user):
        raise LLMError("down")

    llm = MockLLMClient(handler=boom)
    with pytest.raises(AgentError, match="model call failed"):
        SecurityAnalyst(llm, max_retries=3).analyze(ctx)
    assert len(llm.calls) == 1


def test_missing_prompt_file(ctx, tmp_path):
    with pytest.raises(AgentError, match="cannot read prompt"):
        SecurityAnalyst(MockLLMClient(), prompts_dir=tmp_path).analyze(ctx)


def target():
    return ConsensusFinding.from_finding(Finding.model_validate({"agent": "security", **finding_json()}))


def test_challenge_filters_unknown_targets_and_sets_challenger(ctx):
    t = target()
    reply = challenge_reply(
        {"target_id": t.id, "verdict": "Disagree", "reason": "safe here"},
        {"target_id": "ghost", "verdict": "agree", "reason": "x"},
        {"target_id": t.id, "verdict": "maybe", "reason": "x"},
        {"target_id": t.id, "verdict": "agree"},
    )
    llm = MockLLMClient(responses=[reply])
    out = CleanCodeMentor(llm).challenge(ctx, [t])
    assert len(out) == 1 and out[0].challenger == "clean_code" and out[0].verdict == "disagree"
    assert "FINDINGS_JSON" in llm.calls[0][1] and t.id in llm.calls[0][1]


def test_challenge_with_no_findings_makes_no_call(ctx):
    llm = MockLLMClient()
    assert CleanCodeMentor(llm).challenge(ctx, []) == [] and llm.calls == []
