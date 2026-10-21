import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import Config  # noqa: E402
from app.github.diff_parser import parse_diff  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_diff() -> str:
    return (FIXTURES / "sample_diff.patch").read_text(encoding="utf-8")


@pytest.fixture
def sample_files(sample_diff):
    return parse_diff(sample_diff)


@pytest.fixture
def config() -> Config:
    return Config(backend="mock", mode="debate", max_retries=1, max_workers=2)


def finding_json(**over) -> dict:
    base = {
        "title": "SQL injection via f-string query",
        "severity": "high",
        "confidence": 0.9,
        "file_path": "app/users.py",
        "start_line": 12,
        "end_line": 12,
        "evidence": "query = f\"SELECT * FROM users WHERE email = '{email}'\"",
        "explanation": "User input is placed directly in the SQL text.",
        "recommendation": "Use a parameterized query.",
    }
    base.update(over)
    return base


def analysis_reply(*findings: dict) -> str:
    return json.dumps({"summary": "ok", "findings": list(findings)})


def challenge_reply(*challenges: dict) -> str:
    return json.dumps({"challenges": list(challenges)})
