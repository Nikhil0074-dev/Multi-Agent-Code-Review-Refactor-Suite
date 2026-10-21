"""Client for any OpenAI-compatible chat-completions endpoint."""
from __future__ import annotations

import json
from typing import Callable, Optional

from app.http_util import HTTPFailure, request
from app.llm.provider import LLMClient, LLMError


class HostedClient(LLMClient):
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        timeout: int = 120,
        retries: int = 2,
        urlopen: Optional[Callable] = None,
    ) -> None:
        super().__init__()
        if not api_key:
            raise LLMError("API key is required for the hosted backend")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self._urlopen = urlopen

    def _post(self, payload: dict) -> dict:
        _, _, body = request(
            "POST",
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            data=json.dumps(payload).encode("utf-8"),
            timeout=self.timeout,
            urlopen=self._urlopen,
            retries=self.retries,
        )
        try:
            return json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise LLMError(f"model endpoint returned invalid JSON: {exc}") from exc

    def _complete(self, system: str, user: str) -> str:
        payload = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        try:
            try:
                data = self._post(payload)
            except HTTPFailure as exc:
                if exc.status == 400 and "response_format" in exc.body:
                    payload.pop("response_format")
                    data = self._post(payload)
                else:
                    raise
        except HTTPFailure as exc:
            raise LLMError(f"model request failed: {exc}") from exc
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("unexpected response shape from model endpoint") from exc
        if not isinstance(content, str) or not content.strip():
            raise LLMError("model returned empty content")
        return content
