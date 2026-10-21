"""LLM client interface, a scriptable mock client and the client factory."""
from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, Optional

from app.config import Config


class LLMError(RuntimeError):
    """A model call failed (network, auth, bad response shape)."""


@dataclass
class LLMStats:
    calls: int = 0
    prompt_chars: int = 0
    completion_chars: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def record(self, prompt: str, completion: str) -> None:
        with self._lock:
            self.calls += 1
            self.prompt_chars += len(prompt)
            self.completion_chars += len(completion)


class LLMClient(ABC):
    """Anything that can turn (system, user) text into a JSON string."""

    def __init__(self) -> None:
        self.stats = LLMStats()

    @abstractmethod
    def _complete(self, system: str, user: str) -> str:
        """Return the raw model text. Raise LLMError on failure."""

    def complete(self, system: str, user: str) -> str:
        text = self._complete(system, user)
        self.stats.record(system + user, text)
        return text


EMPTY_FINDINGS = '{"summary": "mock", "findings": []}'
EMPTY_CHALLENGES = '{"challenges": []}'


def default_mock_handler(system: str, user: str) -> str:
    if "TASK: CHALLENGE" in user:
        return EMPTY_CHALLENGES
    if "TASK: PATCH" in user:
        return '{"replacement": ""}'
    return EMPTY_FINDINGS


class MockLLMClient(LLMClient):
    """Deterministic client for tests and offline dry runs."""

    def __init__(
        self,
        handler: Optional[Callable[[str, str], str]] = None,
        responses: Optional[list[str]] = None,
    ) -> None:
        super().__init__()
        self._handler = handler or default_mock_handler
        self._responses = list(responses) if responses else []
        self._lock = threading.Lock()
        self.calls: list[tuple[str, str]] = []

    def _complete(self, system: str, user: str) -> str:
        with self._lock:
            self.calls.append((system, user))
            if self._responses:
                return self._responses.pop(0)
        return self._handler(system, user)


def create_client(config: Config) -> LLMClient:
    config.validate()
    if config.backend == "mock":
        return MockLLMClient()
    if config.backend == "local":
        from app.llm.local_client import LocalClient

        return LocalClient(config.ollama_url, config.resolved_model, config.request_timeout, config.max_retries)
    from app.llm.hosted_client import HostedClient

    return HostedClient(
        config.api_key, config.resolved_model, config.base_url, config.request_timeout, config.max_retries
    )
