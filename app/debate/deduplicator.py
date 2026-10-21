"""Merge findings that describe the same problem."""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from app.validation.schemas import SEVERITY_RANK, ConsensusFinding, Finding

LINE_SLACK = 2
TITLE_THRESHOLD = 0.5
STOPWORDS = frozenset(
    "a an the of in on for to and or with without is are be by via from this that use using".split()
)


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOPWORDS}


def title_similarity(a: str, b: str) -> float:
    ratio = SequenceMatcher(None, a.lower(), b.lower()).ratio()
    ta, tb = _tokens(a), _tokens(b)
    jaccard = len(ta & tb) / len(ta | tb) if (ta | tb) else 0.0
    return max(ratio, jaccard)


def is_duplicate(a: Finding, b: Finding) -> bool:
    if a.file_path != b.file_path:
        return False
    near = a.start_line <= b.end_line + LINE_SLACK and b.start_line <= a.end_line + LINE_SLACK
    return near and title_similarity(a.title, b.title) >= TITLE_THRESHOLD


def _rank(f: Finding) -> tuple[int, float]:
    return (SEVERITY_RANK[f.severity], f.confidence)


def deduplicate(findings: list[Finding]) -> list[ConsensusFinding]:
    """Cluster duplicates (transitively) and return one merged finding per cluster."""
    n = len(findings)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        for j in range(i + 1, n):
            if is_duplicate(findings[i], findings[j]):
                parent[find(j)] = find(i)

    clusters: dict[int, list[Finding]] = {}
    for i, f in enumerate(findings):
        clusters.setdefault(find(i), []).append(f)

    merged: list[ConsensusFinding] = []
    for members in clusters.values():
        primary = max(members, key=_rank)
        item = ConsensusFinding.from_finding(primary)
        item.agents = sorted({m.agent for m in members})  # type: ignore[assignment]
        item.merged_ids = sorted({m.finding_id for m in members})
        item.is_hypothesis = all(m.is_hypothesis for m in members)
        item.requires_human_review = any(m.requires_human_review for m in members)
        if item.suggested_patch is None:
            item.suggested_patch = next((m.suggested_patch for m in members if m.suggested_patch), None)
        if len(members) > 1:
            item.notes.append(f"Merged {len(members)} similar findings from: {', '.join(item.agents)}.")
        merged.append(item)

    merged.sort(key=lambda c: (c.file_path, c.start_line, c.id))
    return merged
