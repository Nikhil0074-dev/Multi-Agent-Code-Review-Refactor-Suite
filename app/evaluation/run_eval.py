"""Compare single-agent, independent agents and debate on labelled cases.

Case file format (evaluation/cases/*.json):
  {"id": "...", "diff_file": "relative/path.patch",
   "expected": [{"file_path": "...", "start_line": 1, "end_line": 2}]}
An empty "expected" list marks a clean case.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

from app.config import Config, ConfigError
from app.evaluation.metrics import CaseResult, ExpectedIssue, aggregate
from app.llm.provider import LLMClient, create_client
from app.orchestrator import run_review

MODE_LABELS = {"single": "A single agent", "independent": "B three agents", "debate": "C three agents + debate"}


def load_cases(directory: str | Path) -> list[dict]:
    cases = []
    base = Path(directory)
    for path in sorted(base.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for key in ("id", "diff_file", "expected"):
            if key not in data:
                raise ValueError(f"{path.name}: missing key {key!r}")
        diff_path = (base / data["diff_file"]).resolve()
        data["diff_text"] = diff_path.read_text(encoding="utf-8")
        data["expected"] = [ExpectedIssue(**e) for e in data["expected"]]
        cases.append(data)
    if not cases:
        raise ValueError(f"no case files found in {base}")
    return cases


def evaluate(cases: list[dict], llm: LLMClient, config: Config, modes: Sequence[str]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for mode in modes:
        results: list[CaseResult] = []
        for case in cases:
            report = run_review(case["diff_text"], llm, config, mode=mode, head_sha="eval", base_sha="eval")
            results.append(
                CaseResult(
                    case_id=case["id"],
                    expected=case["expected"],
                    reported=report.findings,
                    duration=report.stats.get("duration_seconds", 0.0),
                    llm_calls=int(report.stats.get("llm_calls", 0)),
                    prompt_chars=int(report.stats.get("prompt_chars", 0)),
                    completion_chars=int(report.stats.get("completion_chars", 0)),
                    failed=report.status == "failed",
                )
            )
        out[mode] = aggregate(results)
    return out


def format_table(results: dict[str, dict[str, float]]) -> str:
    cols = ["precision", "recall", "f1", "false_positive_rate_clean", "duplicate_rate", "avg_latency_seconds", "avg_llm_calls"]
    lines = ["| Configuration | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
    for mode, m in results.items():
        lines.append(f"| {MODE_LABELS.get(mode, mode)} | " + " | ".join(f"{m[c]:.2f}" for c in cols) + " |")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None, *, llm: Optional[LLMClient] = None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.evaluation.run_eval")
    p.add_argument("--cases", default="evaluation/cases")
    p.add_argument("--out", default="review-output/eval-results.json")
    p.add_argument("--backend", choices=["hosted", "local", "mock"])
    p.add_argument("--modes", nargs="+", default=["single", "independent", "debate"],
                   choices=["single", "independent", "debate"])
    args = p.parse_args(argv)
    import os

    env = dict(os.environ)
    if args.backend:
        env["LLM_BACKEND"] = args.backend
    try:
        config = Config.from_env(env)
        cases = load_cases(args.cases)
        client = llm or create_client(config)
    except (ConfigError, ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    results = evaluate(cases, client, config, args.modes)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(format_table(results))
    print(f"\nResults written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
