"""Helpers for pulling a JSON object out of model output."""
from __future__ import annotations

import json
import re


class JSONExtractError(ValueError):
    """Raised when no valid JSON object can be found in text."""


def extract_json_object(text: str) -> dict:
    if not isinstance(text, str) or not text.strip():
        raise JSONExtractError("empty response")
    s = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", s, re.DOTALL | re.IGNORECASE)
    if fence:
        s = fence.group(1)
    try:
        data = json.loads(s)
    except json.JSONDecodeError:
        start, end = s.find("{"), s.rfind("}")
        if start == -1 or end <= start:
            raise JSONExtractError("no JSON object found in response") from None
        try:
            data = json.loads(s[start : end + 1])
        except json.JSONDecodeError as exc:
            raise JSONExtractError(f"invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise JSONExtractError("top-level JSON value must be an object")
    return data
