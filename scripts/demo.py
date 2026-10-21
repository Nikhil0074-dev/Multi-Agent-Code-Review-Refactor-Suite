"""Offline demo: runs the full pipeline with scripted model replies (no API key needed).

    python scripts/demo.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import Config  # noqa: E402
from app.llm.provider import MockLLMClient  # noqa: E402
from app.orchestrator import run_review  # noqa: E402
from app.reporting.markdown_report import render_markdown  # noqa: E402

SQL = {
    "title": "SQL injection via f-string query", "severity": "high", "confidence": 0.93,
    "file_path": "app/users.py", "start_line": 12, "end_line": 12,
    "evidence": "query = f\"SELECT * FROM users WHERE email = '{email}'\"",
    "explanation": "The email value goes straight into the SQL text, so a crafted email can change the query.",
    "recommendation": "Use a parameterized query: cur.execute('... WHERE email = ?', (email,)).",
}
LOOP = {
    "title": "Query inside a loop (N+1)", "severity": "medium", "confidence": 0.8,
    "file_path": "app/orders.py", "start_line": 11, "end_line": 11,
    "evidence": 'cur.execute("SELECT SUM(amount) FROM orders WHERE user_id = ?", (user.id,))',
    "explanation": "One query runs per user. With many users this gets slow.",
    "recommendation": "Fetch all totals with one GROUP BY query.",
}
FAKE = dict(SQL, title="Command injection via os.system", evidence="os.system(cmd)", severity="critical")


def handler(system, user):
    if "TASK: CHALLENGE" in user:
        return json.dumps({"challenges": []})
    if "Security Analyst" in system:
        return json.dumps({"findings": [SQL, FAKE]})  # FAKE does not exist in the diff
    if "Performance Specialist" in system:
        return json.dumps({"findings": [LOOP]})
    return json.dumps({"findings": []})


if __name__ == "__main__":
    diff = (ROOT / "tests" / "fixtures" / "sample_diff.patch").read_text(encoding="utf-8")
    report = run_review(diff, MockLLMClient(handler=handler), Config(backend="mock"), head_sha="demo")
    print(render_markdown(report))
