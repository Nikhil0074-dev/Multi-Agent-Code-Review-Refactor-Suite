"""Entry point for the trusted publishing job: python -m app.publish

Reads report.json from a previous (read-only) review run and posts it to the pull request.
It never checks out or runs pull request code.
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Optional

from pydantic import ValidationError

from app.config import Config, ConfigError
from app.github.client import GitHubClient, GitHubError
from app.github.publisher import publish_report
from app.reporting.json_report import load_report


def main(env: Optional[dict] = None, *, client: Optional[GitHubClient] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    env = dict(os.environ if env is None else env)
    path = env.get("REPORT_PATH", "").strip()
    if not path:
        print("REPORT_PATH is required", file=sys.stderr)
        return 2
    try:
        config = Config.from_env({**env, "LLM_BACKEND": "mock"})
        report = load_report(path)
    except (ConfigError, OSError, ValidationError, ValueError) as exc:
        print(f"Cannot load report: {exc}", file=sys.stderr)
        return 2
    pr_number = config.pr_number or report.pr_number
    if not pr_number:
        print("PR_NUMBER is required (not set in the environment or the report)", file=sys.stderr)
        return 2
    try:
        gh = client or GitHubClient(config.github_token, config.repository, config.github_api_url)
        result = publish_report(gh, pr_number, report, inline=config.inline_comments)
    except GitHubError as exc:
        print(f"Publishing failed: {exc}", file=sys.stderr)
        return 1
    print(f"{result.status}: {result.detail} (inline={result.inline_posted})")
    for err in result.errors:
        print(f"  note: {err}")
    return 1 if result.status == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
