"""Configuration loaded from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Optional

BACKENDS = ("hosted", "local", "mock")
MODES = ("single", "independent", "debate")


class ConfigError(ValueError):
    """Raised when a configuration value is missing or invalid."""


def _get_int(env: Mapping[str, str], key: str, default: int, minimum: int = 0) -> int:
    raw = env.get(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{key} must be an integer, got {raw!r}") from None
    if value < minimum:
        raise ConfigError(f"{key} must be >= {minimum}, got {value}")
    return value


def _get_float(env: Mapping[str, str], key: str, default: float, low: float, high: float) -> float:
    raw = env.get(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError(f"{key} must be a number, got {raw!r}") from None
    if not (low <= value <= high):
        raise ConfigError(f"{key} must be between {low} and {high}, got {value}")
    return value


def _get_bool(env: Mapping[str, str], key: str, default: bool) -> bool:
    raw = env.get(key)
    if raw is None or raw.strip() == "":
        return default
    value = raw.strip().lower()
    if value in ("1", "true", "yes", "on"):
        return True
    if value in ("0", "false", "no", "off"):
        return False
    raise ConfigError(f"{key} must be true or false, got {raw!r}")


@dataclass(frozen=True)
class Config:
    backend: str = "hosted"
    model: str = ""
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    ollama_url: str = "http://localhost:11434"
    request_timeout: int = 120
    max_retries: int = 2
    max_workers: int = 3
    max_diff_chars: int = 60000
    min_confidence: float = 0.5
    max_challenged: int = 15
    max_report_findings: int = 30
    mode: str = "debate"
    inline_comments: bool = False
    allow_fork_review: bool = False
    enable_patches: bool = False
    patch_test_command: str = ""
    conventions: str = ""
    github_token: str = ""
    github_api_url: str = "https://api.github.com"
    repository: str = ""
    pr_number: Optional[int] = None
    head_sha: str = ""
    base_sha: str = ""
    report_dir: str = "review-output"

    @property
    def resolved_model(self) -> str:
        if self.model:
            return self.model
        if self.backend == "local":
            return "llama3.1"
        return "gpt-4o-mini"

    def validate(self) -> None:
        if self.backend not in BACKENDS:
            raise ConfigError(f"LLM_BACKEND must be one of {BACKENDS}, got {self.backend!r}")
        if self.mode not in MODES:
            raise ConfigError(f"REVIEW_MODE must be one of {MODES}, got {self.mode!r}")
        if self.backend == "hosted" and not self.api_key:
            raise ConfigError("LLM_API_KEY is required when LLM_BACKEND=hosted")

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "Config":
        env = os.environ if env is None else env
        pr_raw = env.get("PR_NUMBER", "").strip()
        pr_number: Optional[int] = None
        if pr_raw:
            try:
                pr_number = int(pr_raw)
            except ValueError:
                raise ConfigError(f"PR_NUMBER must be an integer, got {pr_raw!r}") from None
            if pr_number < 1:
                raise ConfigError("PR_NUMBER must be >= 1")
        cfg = cls(
            backend=env.get("LLM_BACKEND", "hosted").strip().lower() or "hosted",
            model=env.get("LLM_MODEL", "").strip(),
            api_key=env.get("LLM_API_KEY", "").strip(),
            base_url=(env.get("LLM_BASE_URL", "").strip() or "https://api.openai.com/v1").rstrip("/"),
            ollama_url=(env.get("OLLAMA_URL", "").strip() or "http://localhost:11434").rstrip("/"),
            request_timeout=_get_int(env, "LLM_TIMEOUT", 120, 1),
            max_retries=_get_int(env, "LLM_MAX_RETRIES", 2, 0),
            max_workers=_get_int(env, "MAX_WORKERS", 3, 1),
            max_diff_chars=_get_int(env, "MAX_DIFF_CHARS", 60000, 1000),
            min_confidence=_get_float(env, "MIN_CONFIDENCE", 0.5, 0.0, 1.0),
            max_challenged=_get_int(env, "MAX_CHALLENGED", 15, 0),
            max_report_findings=_get_int(env, "MAX_REPORT_FINDINGS", 30, 1),
            mode=env.get("REVIEW_MODE", "debate").strip().lower() or "debate",
            inline_comments=_get_bool(env, "ENABLE_INLINE_COMMENTS", False),
            allow_fork_review=_get_bool(env, "ALLOW_FORK_REVIEW", False),
            enable_patches=_get_bool(env, "ENABLE_PATCHES", False),
            patch_test_command=env.get("PATCH_TEST_COMMAND", "").strip(),
            conventions=env.get("REVIEW_CONVENTIONS", "").strip(),
            github_token=env.get("GITHUB_TOKEN", "").strip(),
            github_api_url=(env.get("GITHUB_API_URL", "").strip() or "https://api.github.com").rstrip("/"),
            repository=env.get("GITHUB_REPOSITORY", "").strip(),
            pr_number=pr_number,
            head_sha=env.get("HEAD_SHA", "").strip(),
            base_sha=env.get("BASE_SHA", "").strip(),
            report_dir=env.get("REPORT_DIR", "").strip() or "review-output",
        )
        cfg.validate()
        return cfg
