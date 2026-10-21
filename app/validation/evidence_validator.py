"""Check that findings point at real, changed code and quote it correctly."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from app.github.diff_parser import FileDiff
from app.validation.schemas import Finding

MAX_SPAN = 200
MAX_RELOCATE_DISTANCE = 15
MIN_EVIDENCE_CHARS = 4


@dataclass
class ValidationResult:
    valid: bool
    reason: str = ""
    finding: Optional[Finding] = None  # possibly with a corrected path or lines


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _evidence_lines(evidence: str) -> list[str]:
    out: list[str] = []
    for line in evidence.splitlines():
        line = re.sub(r"^\s*L?\d+\s*[|+]\s?", "", line)
        line = line.strip()
        if line.startswith("+"):
            line = line[1:]
        n = _norm(line)
        if len(n) >= MIN_EVIDENCE_CHARS:
            out.append(n)
    return out


def resolve_path(path: str, files: dict[str, FileDiff]) -> Optional[str]:
    candidates = [path]
    for prefix in ("./", "a/", "b/"):
        if path.startswith(prefix):
            candidates.append(path[len(prefix):])
    for c in candidates:
        if c in files:
            return c
    return None


def validate_finding(f: Finding, files: dict[str, FileDiff]) -> ValidationResult:
    resolved = resolve_path(f.file_path, files)
    if resolved is None:
        return ValidationResult(False, "file is not part of the changed files")
    fd = files[resolved]
    if fd.binary:
        return ValidationResult(False, "file is binary")
    if fd.status == "deleted":
        return ValidationResult(False, "file was deleted")
    if f.end_line - f.start_line + 1 > MAX_SPAN:
        return ValidationResult(False, f"line range is longer than {MAX_SPAN} lines")
    visible = fd.visible
    if not visible:
        return ValidationResult(False, "no reviewable lines in file")
    evidence = _evidence_lines(f.evidence)
    if not evidence:
        return ValidationResult(False, "evidence does not contain usable code")

    start, end = f.start_line, f.end_line
    range_text = _norm("\n".join(visible[n].text for n in range(start, end + 1) if n in visible))
    if not any(e in range_text for e in evidence):
        first = evidence[0]
        hits = [n for n, ln in visible.items() if first in _norm(ln.text)]
        if not hits:
            return ValidationResult(False, "evidence does not appear in the changed code")
        best = min(hits, key=lambda n: (abs(n - start), n))
        if abs(best - start) > MAX_RELOCATE_DISTANCE:
            return ValidationResult(False, "evidence is not near the cited lines")
        span = end - start
        start = best
        end = best + span if (best + span) in visible else best

    if not any(n in fd.changed_positions for n in range(start, end + 1)):
        return ValidationResult(False, "cited lines do not touch changed code")

    fixed = f.model_copy(update={"file_path": resolved, "start_line": start, "end_line": end})
    return ValidationResult(True, "", fixed)


def validate_findings(
    findings: list[Finding], files: dict[str, FileDiff]
) -> tuple[list[Finding], list[tuple[Finding, str]]]:
    valid: list[Finding] = []
    rejected: list[tuple[Finding, str]] = []
    for f in findings:
        result = validate_finding(f, files)
        if result.valid and result.finding is not None:
            valid.append(result.finding)
        else:
            rejected.append((f, result.reason))
    return valid, rejected
