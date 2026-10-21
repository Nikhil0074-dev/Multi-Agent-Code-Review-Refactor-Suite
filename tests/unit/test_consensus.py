from app.debate.consensus import build_consensus
from app.validation.schemas import Challenge, ConsensusFinding, Finding
from tests.conftest import finding_json


def CF(agent="security", **over):
    return ConsensusFinding.from_finding(Finding.model_validate({"agent": agent, **finding_json(**over)}))


def CH(target, verdict, challenger="clean_code", reason="because", sev=None):
    return Challenge(challenger=challenger, target_id=target.id, verdict=verdict, reason=reason, suggested_severity=sev)


def run(findings, challenges=None, **kw):
    return build_consensus(findings, challenges or {}, **kw)


def test_unchallenged_finding_is_accepted():
    kept, dropped = run([CF()])
    assert kept[0].status == "accepted" and not dropped


def test_agreement_adds_note():
    f = CF()
    kept, _ = run([f], {f.id: [CH(f, "agree")]})
    assert kept[0].status == "accepted" and any("Confirmed" in n for n in kept[0].notes)


def test_disputed_high_severity_is_unresolved_not_dropped():
    f = CF(severity="critical")
    kept, dropped = run([f], {f.id: [CH(f, "disagree"), CH(f, "disagree", "performance")]})
    assert kept[0].status == "unresolved" and not dropped
    assert sum("Disputed" in n for n in kept[0].notes) == 2


def test_disputed_medium_becomes_optional_and_low_is_dropped():
    m = CF(severity="medium", title="Medium thing here")
    low = CF(severity="low", title="Low thing here", start_line=20, end_line=20)
    kept, dropped = run([m, low], {
        m.id: [CH(m, "disagree")],
        low.id: [CH(low, "disagree"), CH(low, "disagree", "performance")],
    })
    assert [k.status for k in kept] == ["optional"] and len(dropped) == 1 and "disputed" in dropped[0].reason


def test_agreement_outweighs_dispute():
    f = CF(severity="medium")
    kept, _ = run([f], {f.id: [CH(f, "agree"), CH(f, "agree", "performance"), CH(f, "disagree")]})
    assert kept[0].status == "accepted"


def test_needs_context_makes_optional():
    f = CF(severity="medium")
    kept, _ = run([f], {f.id: [CH(f, "needs_context")]})
    assert kept[0].status == "optional"


def test_low_confidence_rules():
    low = CF(confidence=0.3, severity="medium", title="Weak medium finding")
    high = CF(confidence=0.3, severity="high", title="Weak high finding", start_line=30, end_line=30)
    kept, dropped = run([low, high], min_confidence=0.5)
    assert [k.severity for k in kept] == ["high"] and kept[0].status == "optional" and len(dropped) == 1


def test_hypothesis_is_optional_and_labelled():
    f = CF("performance", is_hypothesis=True, severity="medium")
    kept, _ = run([f])
    assert kept[0].status == "optional" and any("Hypothesis" in n for n in kept[0].notes)


def test_severity_is_not_changed_by_votes_and_self_votes_ignored():
    f = CF(severity="high")
    kept, _ = run([f], {f.id: [CH(f, "agree", sev="low"), CH(f, "disagree", challenger="security")]})
    assert kept[0].severity == "high" and kept[0].status == "accepted"
    assert any("not applied" in n for n in kept[0].notes)


def test_sorting_limit_and_input_not_mutated():
    items = [CF(severity=s, title=f"Finding number {i}", start_line=i + 1, end_line=i + 1)
             for i, s in enumerate(["low", "critical", "medium", "high"])]
    kept, dropped = run(items, max_findings=3)
    assert [k.severity for k in kept] == ["critical", "high", "medium"] and "limit" in dropped[0].reason
    assert all(i.notes == [] for i in items)
