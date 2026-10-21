"""Render a ConsensusReport as GitHub-flavoured Markdown."""
from __future__ import annotations

import re

from app.validation.schemas import SEVERITY_RANK, ConsensusFinding, ConsensusReport

MAX_BODY_CHARS = 60000
AGENT_LABELS = {
    "security": "Security Analyst",
    "performance": "Performance Specialist",
    "clean_code": "Clean Code Mentor",
    "general": "General Reviewer",
}
MARKER = "<!-- multi-agent-review"


def marker_for(sha: str) -> str:
    return f"{MARKER}:{sha} -->"


def sanitize(text: str) -> str:
    """Model text comes from untrusted code. Stop @mentions and HTML comments."""
    text = re.sub(r"@(?=[A-Za-z0-9_-])", "@\u200b", text)
    return text.replace("<!--", "&lt;!--")


def _fence(code: str, lang: str = "") -> str:
    ticks = "```"
    while ticks in code:
        ticks += "`"
    return f"{ticks}{lang}\n{code.rstrip()}\n{ticks}"


def _agents(f: ConsensusFinding) -> str:
    return ", ".join(AGENT_LABELS.get(a, a) for a in f.agents)


def render_finding(f: ConsensusFinding) -> str:
    loc = f"`{f.file_path}` · line {f.start_line}" + (f"-{f.end_line}" if f.end_line != f.start_line else "")
    tags = [f"Confidence {f.confidence:.2f}", _agents(f)]
    if f.status != "accepted":
        tags.append(f.status.capitalize())
    if f.is_hypothesis:
        tags.append("Hypothesis")
    lines = [
        f"**[{f.severity.capitalize()}] {sanitize(f.title)}**",
        loc,
        "",
        sanitize(f.explanation),
        "",
        f"**Fix:** {sanitize(f.recommendation)}",
    ]
    if f.suggested_patch:
        lines += ["", _fence(f.suggested_patch, "diff")]
        if f.patch_status:
            lines.append(f"_Patch check: {sanitize(f.patch_status)}_")
    for note in f.notes:
        lines.append(f"- _{sanitize(note)}_")
    lines.append(f"<sub>{' · '.join(tags)}</sub>")
    return "\n".join(lines)


def render_inline_comment(f: ConsensusFinding) -> str:
    parts = [f"**[{f.severity.capitalize()}] {sanitize(f.title)}**", "", sanitize(f.explanation), "",
             f"**Fix:** {sanitize(f.recommendation)}"]
    if f.status != "accepted":
        parts.append(f"_{f.status.capitalize()} suggestion._")
    return "\n".join(parts)


def render_markdown(report: ConsensusReport, *, sha: str = "") -> str:
    out = ["## AI Code Review", ""]
    if sha or report.head_sha:
        out += [marker_for(sha or report.head_sha), ""]
    out += [sanitize(report.summary), ""]

    counts = report.severity_counts()
    if report.findings:
        out += ["| Critical | High | Medium | Low | Info |", "|---|---|---|---|---|",
                "| " + " | ".join(str(counts[s]) for s in sorted(SEVERITY_RANK, key=lambda s: -SEVERITY_RANK[s])) + " |", ""]

    main = [f for f in report.findings if f.status in ("accepted", "unresolved")]
    optional = [f for f in report.findings if f.status == "optional"]
    for f in main:
        out += [render_finding(f), "", "---", ""]
    if optional:
        out += ["<details><summary>Optional suggestions (%d)</summary>" % len(optional), ""]
        for f in optional:
            out += [render_finding(f), "", "---", ""]
        out += ["</details>", ""]
    if report.agent_errors:
        out += ["**Problems during review**", ""]
        out += [f"- {sanitize(k)}: {sanitize(v)[:200]}" for k, v in sorted(report.agent_errors.items())]
        out.append("")
    if report.dropped:
        out.append(f"_{len(report.dropped)} candidate finding(s) were removed by validation or peer review._")
    if report.skipped_files:
        out.append(f"_{len(report.skipped_files)} file(s) were not fully reviewed: "
                   + sanitize(", ".join(report.skipped_files[:10])) + ("..." if len(report.skipped_files) > 10 else "") + "_")
    out.append("")
    out.append("_Automated review. Findings can be wrong. A human should confirm before acting._")
    text = "\n".join(out)
    if len(text) > MAX_BODY_CHARS:
        text = text[: MAX_BODY_CHARS - 80].rstrip() + "\n\n_Report truncated. See the report.json artifact for all findings._"
    return text
