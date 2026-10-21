"""Pydantic schemas for findings, debate statements and the consensus report."""
from __future__ import annotations

import hashlib
import re
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

AgentName = Literal["security", "performance", "clean_code", "general"]
Severity = Literal["critical", "high", "medium", "low", "info"]
Verdict = Literal["agree", "disagree", "needs_context"]
FindingStatus = Literal["accepted", "optional", "unresolved"]
ReportStatus = Literal["ok", "no_findings", "partial", "failed"]

SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}


def normalize_repo_path(path: str) -> str:
    """Return a clean repository-relative path, or raise ValueError."""
    if not isinstance(path, str):
        raise ValueError("path must be a string")
    p = path.strip().replace("\\", "/")
    if not p:
        raise ValueError("path is empty")
    if "\x00" in p:
        raise ValueError("path contains a null byte")
    if p.startswith("/") or re.match(r"^[A-Za-z]:", p):
        raise ValueError("path must be relative to the repository")
    parts = [x for x in p.split("/") if x not in ("", ".")]
    if not parts or ".." in parts:
        raise ValueError("path is unsafe")
    return "/".join(parts)


def is_safe_repo_path(path: str) -> bool:
    try:
        normalize_repo_path(path)
    except ValueError:
        return False
    return True


class Finding(BaseModel):
    """One issue reported by one agent."""

    agent: AgentName
    title: str = Field(min_length=5, max_length=160)
    severity: Severity
    confidence: float = Field(ge=0.0, le=1.0)
    file_path: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    evidence: str = Field(min_length=1)
    explanation: str = Field(min_length=1)
    recommendation: str = Field(min_length=1)
    suggested_patch: Optional[str] = None
    is_hypothesis: bool = False
    requires_human_review: bool = True

    @field_validator("title", mode="before")
    @classmethod
    def _trim_title(cls, v):
        if isinstance(v, str):
            v = " ".join(v.split())
            return v[:160]
        return v

    @field_validator("severity", mode="before")
    @classmethod
    def _lower_severity(cls, v):
        return v.strip().lower() if isinstance(v, str) else v

    @field_validator("confidence", mode="before")
    @classmethod
    def _percent_to_fraction(cls, v):
        if isinstance(v, (int, float)) and not isinstance(v, bool) and 1 < v <= 100:
            return v / 100.0
        return v

    @field_validator("file_path")
    @classmethod
    def _safe_path(cls, v: str) -> str:
        return normalize_repo_path(v)

    @model_validator(mode="after")
    def _check_range(self):
        if self.end_line < self.start_line:
            raise ValueError("end_line must be >= start_line")
        return self

    @property
    def finding_id(self) -> str:
        key = f"{self.agent}|{self.file_path}|{self.start_line}|{self.title.lower()}"
        return hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]


class AgentReview(BaseModel):
    agent: AgentName
    findings: list[Finding] = Field(default_factory=list)
    summary: str = ""
    rejected: list[str] = Field(default_factory=list)


class Challenge(BaseModel):
    """One agent's reaction to another agent's finding."""

    challenger: AgentName
    target_id: str = Field(min_length=1)
    verdict: Verdict
    reason: str = Field(min_length=1)
    suggested_severity: Optional[Severity] = None

    @field_validator("verdict", mode="before")
    @classmethod
    def _norm_verdict(cls, v):
        return v.strip().lower().replace(" ", "_") if isinstance(v, str) else v

    @field_validator("suggested_severity", mode="before")
    @classmethod
    def _norm_sev(cls, v):
        if isinstance(v, str):
            v = v.strip().lower()
            return v or None
        return v


class ConsensusFinding(BaseModel):
    """A finding after merging, challenge and validation."""

    id: str
    title: str
    severity: Severity
    confidence: float = Field(ge=0.0, le=1.0)
    file_path: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    evidence: str
    explanation: str
    recommendation: str
    suggested_patch: Optional[str] = None
    agents: list[AgentName]
    status: FindingStatus = "accepted"
    is_hypothesis: bool = False
    requires_human_review: bool = True
    merged_ids: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    patch_status: Optional[str] = None

    @classmethod
    def from_finding(cls, f: Finding) -> "ConsensusFinding":
        return cls(
            id=f.finding_id,
            title=f.title,
            severity=f.severity,
            confidence=f.confidence,
            file_path=f.file_path,
            start_line=f.start_line,
            end_line=f.end_line,
            evidence=f.evidence,
            explanation=f.explanation,
            recommendation=f.recommendation,
            suggested_patch=f.suggested_patch,
            agents=[f.agent],
            is_hypothesis=f.is_hypothesis,
            requires_human_review=f.requires_human_review,
            merged_ids=[f.finding_id],
        )


class DroppedFinding(BaseModel):
    id: str
    title: str
    file_path: str
    reason: str


class ConsensusReport(BaseModel):
    version: str = "1"
    status: ReportStatus = "ok"
    mode: str = "debate"
    head_sha: str = ""
    base_sha: str = ""
    pr_number: Optional[int] = None
    summary: str = ""
    findings: list[ConsensusFinding] = Field(default_factory=list)
    dropped: list[DroppedFinding] = Field(default_factory=list)
    agent_errors: dict[str, str] = Field(default_factory=dict)
    skipped_files: list[str] = Field(default_factory=list)
    stats: dict[str, float] = Field(default_factory=dict)

    def severity_counts(self) -> dict[str, int]:
        counts = {name: 0 for name in SEVERITY_RANK}
        for f in self.findings:
            counts[f.severity] += 1
        return counts
