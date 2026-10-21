"""Turn merged findings plus peer challenges into the final list."""
from __future__ import annotations

from typing import Mapping, Sequence

from app.validation.schemas import SEVERITY_RANK, Challenge, ConsensusFinding, DroppedFinding

HIGH_IMPACT = ("critical", "high")
LOW_IMPACT = ("low", "info")


def _shorten(text: str, limit: int = 200) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def sort_key(f: ConsensusFinding) -> tuple:
    return (-SEVERITY_RANK[f.severity], -f.confidence, f.file_path, f.start_line)


def build_consensus(
    findings: Sequence[ConsensusFinding],
    challenges: Mapping[str, Sequence[Challenge]],
    *,
    min_confidence: float = 0.5,
    max_findings: int = 30,
) -> tuple[list[ConsensusFinding], list[DroppedFinding]]:
    kept: list[ConsensusFinding] = []
    dropped: list[DroppedFinding] = []

    def drop(f: ConsensusFinding, reason: str) -> None:
        dropped.append(DroppedFinding(id=f.id, title=f.title, file_path=f.file_path, reason=reason))

    for original in findings:
        f = original.model_copy(deep=True)
        votes = [c for c in challenges.get(f.id, []) if c.challenger not in f.agents]
        agree = [c for c in votes if c.verdict == "agree"]
        disagree = [c for c in votes if c.verdict == "disagree"]
        unsure = [c for c in votes if c.verdict == "needs_context"]
        high_impact = f.severity in HIGH_IMPACT

        if f.confidence < min_confidence:
            if not high_impact:
                drop(f, f"low confidence ({f.confidence:.2f} < {min_confidence:.2f})")
                continue
            f.status = "optional"
            f.notes.append(f"Low confidence ({f.confidence:.2f}); kept because severity is {f.severity}.")

        if len(disagree) > len(agree):
            for c in disagree:
                f.notes.append(f"Disputed by {c.challenger}: {_shorten(c.reason)}")
            if high_impact:
                f.status = "unresolved"
            elif f.severity in LOW_IMPACT and len(disagree) >= 2 and not agree:
                drop(f, "disputed by multiple reviewers")
                continue
            elif f.status == "accepted":
                f.status = "optional"
        elif len(unsure) > len(agree) and f.status == "accepted":
            f.status = "optional"
            for c in unsure:
                f.notes.append(f"Needs context ({c.challenger}): {_shorten(c.reason)}")
        else:
            for c in agree:
                f.notes.append(f"Confirmed by {c.challenger}.")

        for c in votes:
            if c.suggested_severity and c.suggested_severity != f.severity:
                f.notes.append(f"{c.challenger} suggested severity '{c.suggested_severity}' (not applied).")

        if f.is_hypothesis:
            f.notes.append("Hypothesis: not backed by profiling or a clear complexity argument.")
            if f.status == "accepted":
                f.status = "optional"

        kept.append(f)

    kept.sort(key=sort_key)
    if len(kept) > max_findings:
        for f in kept[max_findings:]:
            drop(f, f"report limit of {max_findings} findings reached")
        kept = kept[:max_findings]
    return kept, dropped
