"""Write and read the machine-readable report."""
from __future__ import annotations

from pathlib import Path

from app.reporting.markdown_report import render_markdown
from app.validation.schemas import ConsensusReport


def write_reports(report: ConsensusReport, out_dir: str | Path) -> tuple[Path, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "report.json"
    md_path = out / "report.md"
    json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


def load_report(path: str | Path) -> ConsensusReport:
    return ConsensusReport.model_validate_json(Path(path).read_text(encoding="utf-8"))
