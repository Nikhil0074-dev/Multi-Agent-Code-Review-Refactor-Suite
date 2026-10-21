"""Runs the review: analysis, validation, dedupe, peer challenge, consensus."""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from app.agents import (
    CleanCodeMentor,
    GeneralAgent,
    PerformanceSpecialist,
    SecurityAnalyst,
)
from app.agents.base import BaseAgent
from app.config import MODES, Config
from app.context import ReviewContext, build_chunks, select_reviewable
from app.debate.consensus import build_consensus, sort_key
from app.debate.deduplicator import deduplicate
from app.debate.peer_challenge import run_peer_challenge
from app.github.diff_parser import parse_diff
from app.llm.provider import LLMClient
from app.validation.evidence_validator import validate_findings
from app.validation.schemas import (
    ConsensusFinding,
    ConsensusReport,
    DroppedFinding,
    Finding,
)

log = logging.getLogger(__name__)


def make_agents(mode: str, llm: LLMClient, config: Config) -> list[BaseAgent]:
    classes = [GeneralAgent] if mode == "single" else [SecurityAnalyst, PerformanceSpecialist, CleanCodeMentor]
    return [c(llm, max_retries=config.max_retries, conventions=config.conventions) for c in classes]


def _severity_text(counts: dict[str, int]) -> str:
    parts = [f"{n} {name}" for name, n in counts.items() if n]
    return ", ".join(parts)


def run_review(
    diff_text: str,
    llm: LLMClient,
    config: Config,
    *,
    head_sha: str = "",
    base_sha: str = "",
    pr_number: Optional[int] = None,
    mode: Optional[str] = None,
) -> ConsensusReport:
    mode = mode or config.mode
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    started = time.monotonic()
    calls_before = llm.stats.calls
    meta = dict(mode=mode, head_sha=head_sha, base_sha=base_sha, pr_number=pr_number)

    files = parse_diff(diff_text)
    reviewable, skipped = select_reviewable(files)
    if not reviewable:
        return ConsensusReport(
            status="no_findings",
            summary="No reviewable code changes were found.",
            skipped_files=skipped,
            **meta,
        )

    chunks, truncated = build_chunks(reviewable, config.max_diff_chars)
    skipped = skipped + [f"{p} (truncated to fit size limit)" for p in truncated]
    file_map = {fd.path: fd for fd in reviewable}
    agents = make_agents(mode, llm, config)

    # Round 1: independent analysis
    jobs = [
        (agent, ReviewContext(files=chunk, head_sha=head_sha, base_sha=base_sha, conventions=config.conventions))
        for chunk in chunks
        for agent in agents
    ]
    raw_findings: list[Finding] = []
    errors: dict[str, str] = {}
    succeeded = 0
    rejected_by_schema = 0
    with ThreadPoolExecutor(max_workers=config.max_workers) as pool:
        futures = [(agent, pool.submit(agent.analyze, ctx)) for agent, ctx in jobs]
        for agent, fut in futures:
            try:
                review = fut.result()
            except Exception as exc:  # noqa: BLE001 - record and continue with other agents
                log.warning("agent %s failed: %s", agent.name, exc)
                errors.setdefault(agent.name, str(exc))
                continue
            succeeded += 1
            raw_findings.extend(review.findings)
            rejected_by_schema += len(review.rejected)

    def finish(report: ConsensusReport) -> ConsensusReport:
        report.stats = {
            "duration_seconds": round(time.monotonic() - started, 3),
            "llm_calls": float(llm.stats.calls - calls_before),
            "prompt_chars": float(llm.stats.prompt_chars),
            "completion_chars": float(llm.stats.completion_chars),
            "schema_rejected": float(rejected_by_schema),
        }
        return report

    if succeeded == 0:
        return finish(
            ConsensusReport(
                status="failed",
                summary="Review failed: every model call failed. No findings were produced.",
                agent_errors=errors,
                skipped_files=skipped,
                **meta,
            )
        )

    # Evidence validation (free, so it runs before any debate tokens are spent)
    valid, rejected = validate_findings(raw_findings, file_map)
    dropped = [
        DroppedFinding(id=f.finding_id, title=f.title, file_path=f.file_path, reason=f"evidence check: {why}")
        for f, why in rejected
    ]

    if mode == "debate":
        merged = deduplicate(valid)
        challenges, challenge_errors = run_peer_challenge(
            agents,
            file_map,
            merged,
            max_challenged=config.max_challenged,
            max_chars=config.max_diff_chars,
            max_workers=config.max_workers,
            head_sha=head_sha,
            base_sha=base_sha,
            conventions=config.conventions,
        )
        for name, msg in challenge_errors.items():
            errors.setdefault(f"{name} (challenge)", msg)
        kept, consensus_dropped = build_consensus(
            merged,
            challenges,
            min_confidence=config.min_confidence,
            max_findings=config.max_report_findings,
        )
        dropped.extend(consensus_dropped)
    else:
        kept = sorted((ConsensusFinding.from_finding(f) for f in valid), key=sort_key)

    report = ConsensusReport(findings=kept, dropped=dropped, agent_errors=errors, skipped_files=skipped, **meta)
    counts = report.severity_counts()
    if errors:
        report.status = "partial"
        failed = ", ".join(sorted(errors))
        report.summary = f"Review incomplete: some model calls failed ({failed}). "
    elif kept:
        report.status = "ok"
    else:
        report.status = "no_findings"
    if kept:
        report.summary += f"{len(kept)} finding(s): {_severity_text(counts)}."
    else:
        report.summary += "No actionable findings."
    return finish(report)
