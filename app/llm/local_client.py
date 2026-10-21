"""Client for a local Ollama server (code stays on your own machine)."""
from __future__ import annotations

import json
from typing import Callable, Optional

from app.http_util import HTTPFailure, request
from app.llm.provider import LLMClient, LLMError


class LocalClient(LLMClient):
    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "llama3.1",
        timeout: int = 300,
        retries: int = 1,
        urlopen: Optional[Callable] = None,
    ) -> None:
        super().__init__()
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.retries = retries
        self._urlopen = urlopen

    def _complete(self, system: str, user: str) -> str:
        payload = {
            "model": self.model,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        try:
            _, _, body = request(
                "POST",
                f"{self.base_url}/api/chat",
                headers={"Content-Type": "application/json"},
                data=json.dumps(payload).encode("utf-8"),
                timeout=self.timeout,
                urlopen=self._urlopen,
                retries=self.retries,
            )
        except HTTPFailure as exc:
            raise LLMError(f"local model request failed: {exc}") from exc
        try:
            content = json.loads(body.decode("utf-8"))["message"]["content"]
        except (ValueError, KeyError, TypeError, UnicodeDecodeError) as exc:
            raise LLMError("unexpected response shape from local model") from exc
        if not isinstance(content, str) or not content.strip():
            raise LLMError("local model returned empty content")
        return content
