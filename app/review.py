"""Entry point: python -m app.review"""
from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional, Sequence

from app.config import Config, ConfigError
from app.github.client import GitHubClient, GitHubError
from app.github.pull_request import load_pull_request
from app.llm.provider import LLMClient, create_client
from app.orchestrator import run_review
from app.reporting.json_report import write_reports
from app.reporting.markdown_report import render_markdown

log = logging.getLogger("review")


def _git_diff(base: str, head: str) -> str:
    if not (base and head):
        raise RuntimeError("BASE_SHA and HEAD_SHA are required to compute a local git diff")
    proc = subprocess.run(
        ["git", "diff", "--no-color", "--unified=3", f"{base}...{head}"],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git diff failed: {proc.stderr.strip()[:300]}")
    return proc.stdout


def _parse_args(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m app.review", description="Run the multi-agent review.")
    p.add_argument("--diff-file", help="Review this unified diff file instead of fetching one")
    p.add_argument("--out-dir", help="Directory for report.json and report.md")
    p.add_argument("--backend", choices=["hosted", "local", "mock"], help="Override LLM_BACKEND")
    p.add_argument("--mode", choices=["single", "independent", "debate"], help="Override REVIEW_MODE")
    return p.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None, *, llm: Optional[LLMClient] = None, env: Optional[dict] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _parse_args(argv)
    env = dict(os.environ if env is None else env)
    if args.backend:
        env["LLM_BACKEND"] = args.backend
    if args.mode:
        env["REVIEW_MODE"] = args.mode
    if args.out_dir:
        env["REPORT_DIR"] = args.out_dir
    diff_file = args.diff_file or env.get("DIFF_FILE", "")
    try:
        config = Config.from_env(env)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    head_sha, base_sha = config.head_sha, config.base_sha
    try:
        if diff_file:
            diff_text = Path(diff_file).read_text(encoding="utf-8", errors="replace")
        elif config.github_token and config.repository and config.pr_number:
            client = GitHubClient(config.github_token, config.repository, config.github_api_url)
            pr = load_pull_request(client, config.pr_number)
            if pr.is_fork and not config.allow_fork_review:
                print("Skipping: pull request is from a fork (set ALLOW_FORK_REVIEW=true to override).")
                return 0
            head_sha, base_sha = pr.head_sha, pr.base_sha
            try:
                diff_text = client.get_pull_diff(config.pr_number)
            except GitHubError as exc:
                log.warning("API diff failed (%s); falling back to git diff", exc)
                diff_text = _git_diff(base_sha, head_sha)
        else:
            diff_text = _git_diff(base_sha, head_sha)
    except (OSError, GitHubError, RuntimeError) as exc:
        print(f"Could not get the diff: {exc}", file=sys.stderr)
        return 2

    try:
        client_llm = llm or create_client(config)
    except Exception as exc:  # noqa: BLE001 - report any backend setup problem
        print(f"Could not set up the model backend: {exc}", file=sys.stderr)
        return 2

    report = run_review(diff_text, client_llm, config, head_sha=head_sha, base_sha=base_sha, pr_number=config.pr_number)

    if config.enable_patches and report.findings and report.status != "failed":
        from app.refactor.patch_generator import suggest_patches

        n = suggest_patches(report, Path.cwd(), client_llm, config)
        log.info("attached %d validated patch suggestion(s)", n)

    json_path, md_path = write_reports(report, config.report_dir)
    summary_file = env.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        try:
            with open(summary_file, "a", encoding="utf-8") as fh:
                fh.write(render_markdown(report) + "\n")
        except OSError as exc:
            log.warning("could not write step summary: %s", exc)
    print(f"{report.status}: {report.summary}")
    print(f"Reports written to {json_path} and {md_path}")
    return 1 if report.status == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
