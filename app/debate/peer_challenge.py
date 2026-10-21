"""Round 2: each agent reviews the other agents' findings."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Sequence

from app.agents.base import BaseAgent
from app.context import ReviewContext, build_chunks
from app.github.diff_parser import FileDiff
from app.validation.schemas import SEVERITY_RANK, Challenge, ConsensusFinding


def select_for_challenge(findings: Sequence[ConsensusFinding], limit: int) -> list[ConsensusFinding]:
    """Most severe and most confident first, capped to control cost."""
    ranked = sorted(findings, key=lambda f: (-SEVERITY_RANK[f.severity], -f.confidence, f.id))
    return ranked[: max(0, limit)]


def run_peer_challenge(
    agents: Sequence[BaseAgent],
    files: dict[str, FileDiff],
    findings: Sequence[ConsensusFinding],
    *,
    max_challenged: int,
    max_chars: int,
    max_workers: int = 3,
    head_sha: str = "",
    base_sha: str = "",
    conventions: str = "",
) -> tuple[dict[str, list[Challenge]], dict[str, str]]:
    """Return (challenges by finding id, errors by agent name)."""
    selected = select_for_challenge(findings, max_challenged)
    if len(agents) < 2 or not selected:
        return {}, {}

    paths = sorted({f.file_path for f in selected})
    subset = [files[p] for p in paths if p in files]
    chunks, _ = build_chunks(subset, max_chars)

    jobs: list[tuple[BaseAgent, ReviewContext, list[ConsensusFinding]]] = []
    for chunk in chunks:
        chunk_paths = {fd.path for fd in chunk}
        for agent in agents:
            targets = [f for f in selected if f.file_path in chunk_paths and agent.name not in f.agents]
            if targets:
                ctx = ReviewContext(files=chunk, head_sha=head_sha, base_sha=base_sha, conventions=conventions)
                jobs.append((agent, ctx, targets))

    result: dict[str, list[Challenge]] = {}
    errors: dict[str, str] = {}
    if not jobs:
        return result, errors

    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
        futures = [(agent, pool.submit(agent.challenge, ctx, targets)) for agent, ctx, targets in jobs]
        for agent, fut in futures:
            try:
                for ch in fut.result():
                    result.setdefault(ch.target_id, []).append(ch)
            except Exception as exc:  # noqa: BLE001 - one failed challenge must not stop the review
                errors.setdefault(agent.name, str(exc))
    return result, errors
