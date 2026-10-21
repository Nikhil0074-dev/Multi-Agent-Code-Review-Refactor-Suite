"""Validate and test suggested patches in a throw-away copy. The real repo is never touched."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional, Sequence

from app.github.diff_parser import FileDiff, parse_diff
from app.validation.schemas import is_safe_repo_path

MAX_CHANGED_LINES = 200


class PatchError(ValueError):
    """The patch is invalid or does not apply."""


@dataclass
class PatchValidation:
    valid: bool
    errors: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    added: int = 0
    removed: int = 0
    new_contents: dict[str, str] = field(default_factory=dict)


def _same(a: str, b: str) -> bool:
    return a.rstrip("\r\n") == b.rstrip("\r\n")


def apply_file_patch(original: str, fd: FileDiff) -> str:
    """Apply one file's hunks to text. Raises PatchError on any mismatch."""
    orig = original.splitlines(keepends=True)
    out: list[str] = []
    cursor = 0
    for ln in fd.lines:
        target = (ln.old_no - 1) if ln.kind in ("context", "remove") and ln.old_no else ln.old_next - 1
        if target < cursor:
            raise PatchError("hunks overlap or are out of order")
        if target > len(orig):
            raise PatchError("hunk starts beyond the end of the file")
        out.extend(orig[cursor:target])
        cursor = target
        if ln.kind == "add":
            out.append(ln.text + "\n")
            continue
        if cursor >= len(orig) or not _same(orig[cursor], ln.text):
            raise PatchError(f"context mismatch at original line {cursor + 1}")
        if ln.kind == "context":
            out.append(orig[cursor])
        cursor += 1
    out.extend(orig[cursor:])
    return "".join(out)


def validate_patch(
    patch_text: str,
    originals: Mapping[str, str],
    allowed_paths: Optional[set[str]] = None,
    max_changed_lines: int = MAX_CHANGED_LINES,
) -> PatchValidation:
    result = PatchValidation(valid=False)
    if not patch_text or not patch_text.strip():
        result.errors.append("patch is empty")
        return result
    parsed = parse_diff(patch_text)
    if not parsed:
        result.errors.append("patch contains no file changes")
        return result
    for path, fd in parsed.items():
        if not is_safe_repo_path(path):
            result.errors.append(f"unsafe path: {path!r}")
            continue
        if allowed_paths is not None and path not in allowed_paths:
            result.errors.append(f"path is outside the allowed files: {path}")
            continue
        if fd.binary or fd.status != "modified" or fd.old_path != fd.path:
            result.errors.append(f"only in-place edits are allowed ({path}: {fd.status})")
            continue
        if path not in originals:
            result.errors.append(f"original content for {path} is not available")
            continue
        result.added += fd.additions
        result.removed += fd.removals
        try:
            result.new_contents[path] = apply_file_patch(originals[path], fd)
        except PatchError as exc:
            result.errors.append(f"{path}: {exc}")
            continue
        result.files.append(path)
    if result.added + result.removed > max_changed_lines:
        result.errors.append(f"patch changes more than {max_changed_lines} lines")
    if result.added + result.removed == 0 and not result.errors:
        result.errors.append("patch changes nothing")
    result.valid = not result.errors
    if not result.valid:
        result.new_contents = {}
    return result


_IGNORE = shutil.ignore_patterns(".git", "node_modules", "__pycache__", ".venv", "venv", ".pytest_cache")


def run_checks(
    repo_root: str | Path,
    new_contents: Mapping[str, str],
    command: Sequence[str],
    timeout: int = 300,
) -> tuple[bool, str]:
    """Copy the repo, write the patched files, run command (no shell, no secrets in env).

    This is NOT a security sandbox. Run the whole workflow in an isolated runner or container.
    """
    root = Path(repo_root).resolve()
    if not command:
        raise PatchError("test command is empty")
    with tempfile.TemporaryDirectory(prefix="patch-check-") as tmp:
        work = Path(tmp) / "repo"
        shutil.copytree(root, work, ignore=_IGNORE)
        for rel, text in new_contents.items():
            if not is_safe_repo_path(rel):
                raise PatchError(f"unsafe path: {rel!r}")
            dest = (work / rel).resolve()
            if work.resolve() not in dest.parents:
                raise PatchError(f"path escapes the repository: {rel!r}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(text, encoding="utf-8")
        env = {"PATH": os.environ.get("PATH", ""), "HOME": tmp, "LANG": "C.UTF-8", "CI": "1"}
        try:
            proc = subprocess.run(
                list(command), cwd=work, env=env, capture_output=True, text=True, timeout=timeout, check=False
            )
        except subprocess.TimeoutExpired:
            return False, f"timed out after {timeout}s"
        except OSError as exc:
            return False, f"could not run command: {exc}"
        output = (proc.stdout + proc.stderr)[-2000:]
        return proc.returncode == 0, output
