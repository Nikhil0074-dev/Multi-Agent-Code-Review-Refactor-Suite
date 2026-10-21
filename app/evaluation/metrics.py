"""Precision, recall, F1 and friends for comparing review configurations."""
from __future__ import annotations

from dataclasses import dataclass, field

from app.validation.schemas import ConsensusFinding


@dataclass(frozen=True)
class ExpectedIssue:
    file_path: str
    start_line: int
    end_line: int


@dataclass
class CaseResult:
    case_id: str
    expected: list[ExpectedIssue]
    reported: list[ConsensusFinding]
    duration: float = 0.0
    llm_calls: int = 0
    prompt_chars: int = 0
    completion_chars: int = 0
    failed: bool = False


@dataclass
class MatchCounts:
    true_positives: int = 0
    false_positives: int = 0
    duplicates: int = 0
    exact_locations: int = 0
    matched_expected: set[int] = field(default_factory=set)


def overlaps(f: ConsensusFinding, e: ExpectedIssue, tolerance: int) -> bool:
    return (
        f.file_path == e.file_path
        and f.start_line <= e.end_line + tolerance
        and e.start_line <= f.end_line + tolerance
    )


def match_case(result: CaseResult, tolerance: int = 3) -> MatchCounts:
    """Greedy one-to-one matching. A second hit on an already-found issue is a duplicate."""
    counts = MatchCounts()
    for f in result.reported:
        hit_free = next(
            (i for i, e in enumerate(result.expected) if i not in counts.matched_expected and overlaps(f, e, tolerance)),
            None,
        )
        if hit_free is not None:
            counts.matched_expected.add(hit_free)
            counts.true_positives += 1
            if overlaps(f, result.expected[hit_free], 0):
                counts.exact_locations += 1
        elif any(overlaps(f, e, tolerance) for e in result.expected):
            counts.duplicates += 1
        else:
            counts.false_positives += 1
    return counts


def _ratio(num: float, den: float) -> float:
    return num / den if den else 0.0


def aggregate(results: list[CaseResult], tolerance: int = 3) -> dict[str, float]:
    """Micro-averaged metrics over all cases. Ratios are 0.0 when the denominator is 0."""
    tp = fp = dup = exact = reported = expected = 0
    clean_cases = clean_with_findings = 0
    for r in results:
        c = match_case(r, tolerance)
        tp += c.true_positives
        fp += c.false_positives
        dup += c.duplicates
        exact += c.exact_locations
        reported += len(r.reported)
        expected += len(r.expected)
        if not r.expected:
            clean_cases += 1
            if r.reported:
                clean_with_findings += 1
    precision = _ratio(tp, reported)
    recall = _ratio(tp, expected)
    return {
        "cases": float(len(results)),
        "reported": float(reported),
        "expected": float(expected),
        "true_positives": float(tp),
        "false_positives": float(fp),
        "duplicates": float(dup),
        "precision": precision,
        "recall": recall,
        "f1": _ratio(2 * precision * recall, precision + recall),
        "false_positive_rate_clean": _ratio(clean_with_findings, clean_cases),
        "localization_accuracy": _ratio(exact, tp),
        "duplicate_rate": _ratio(dup, reported),
        "avg_latency_seconds": _ratio(sum(r.duration for r in results), len(results)),
        "avg_llm_calls": _ratio(sum(r.llm_calls for r in results), len(results)),
        "avg_prompt_chars": _ratio(sum(r.prompt_chars for r in results), len(results)),
        "failed_cases": float(sum(1 for r in results if r.failed)),
    }
