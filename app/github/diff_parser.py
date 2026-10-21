"""Parse unified diffs into per-file line information."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import cached_property
from typing import Optional

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass
class DiffLine:
    kind: str  # "add", "context" or "remove"
    text: str
    hunk: int
    old_no: Optional[int] = None  # set for context and remove lines
    new_no: Optional[int] = None  # set for context and add lines
    old_next: int = 0  # next old-file line number before this line
    new_next: int = 0  # next new-file line number before this line


@dataclass
class FileDiff:
    path: str
    old_path: str = ""
    status: str = "modified"  # added, deleted, modified, renamed
    binary: bool = False
    hunks: int = 0
    lines: list[DiffLine] = field(default_factory=list)

    @cached_property
    def visible(self) -> dict[int, DiffLine]:
        """New-file line number -> line, for lines shown in the diff."""
        return {ln.new_no: ln for ln in self.lines if ln.new_no is not None}

    @cached_property
    def added(self) -> set[int]:
        return {ln.new_no for ln in self.lines if ln.kind == "add" and ln.new_no is not None}

    @cached_property
    def changed_positions(self) -> set[int]:
        """Added lines, plus the lines around each removal."""
        positions = set(self.added)
        for ln in self.lines:
            if ln.kind == "remove":
                positions.add(ln.new_next)
                positions.add(ln.new_next - 1)
        return positions

    @property
    def additions(self) -> int:
        return len(self.added)

    @property
    def removals(self) -> int:
        return sum(1 for ln in self.lines if ln.kind == "remove")


def _unquote(p: str) -> str:
    p = p.strip()
    if len(p) >= 2 and p.startswith('"') and p.endswith('"'):
        return p[1:-1]
    return p


def _header_path(raw: str, prefix: str) -> Optional[str]:
    """Path from a '--- ' or '+++ ' line. None means /dev/null."""
    p = _unquote(raw.split("\t")[0])
    if p == "/dev/null":
        return None
    if p.startswith(prefix):
        p = p[len(prefix):]
    return p


def _split_git_header(rest: str) -> tuple[str, str]:
    rest = rest.strip()
    mid = len(rest) // 2
    if len(rest) % 2 == 1 and rest[mid] == " ":
        left, right = rest[:mid], rest[mid + 1 :]
        if left.startswith("a/") and right.startswith("b/") and left[2:] == right[2:]:
            return left[2:], right[2:]
    idx = rest.find(" b/")
    if rest.startswith("a/") and idx != -1:
        return rest[2:idx], rest[idx + 3 :]
    parts = rest.split(" ")
    if len(parts) >= 2:
        return parts[0], parts[-1]
    return rest, rest


def parse_diff(text: str) -> dict[str, FileDiff]:
    """Parse a unified (git-style or plain) diff. Keys are new-file paths."""
    ordered: list[FileDiff] = []
    cur: Optional[FileDiff] = None
    old_no = new_no = old_rem = new_rem = hunk = 0

    for raw in text.splitlines():
        if (old_rem > 0 or new_rem > 0) and cur is not None:
            if raw.startswith("\\"):
                continue
            tag, body = raw[:1], raw[1:]
            if tag == "+" and new_rem > 0:
                cur.lines.append(DiffLine("add", body, hunk, None, new_no, old_no, new_no))
                new_no += 1
                new_rem -= 1
                continue
            if tag == "-" and old_rem > 0:
                cur.lines.append(DiffLine("remove", body, hunk, old_no, None, old_no, new_no))
                old_no += 1
                old_rem -= 1
                continue
            if (tag == " " or raw == "") and old_rem > 0 and new_rem > 0:
                cur.lines.append(DiffLine("context", body, hunk, old_no, new_no, old_no, new_no))
                old_no += 1
                new_no += 1
                old_rem -= 1
                new_rem -= 1
                continue
            old_rem = new_rem = 0  # malformed hunk: resynchronise

        if raw.startswith("diff --git "):
            a, b = _split_git_header(raw[len("diff --git "):])
            cur = FileDiff(path=b, old_path=a)
            ordered.append(cur)
            hunk = 0
        elif raw.startswith("--- "):
            p = _header_path(raw[4:], "a/")
            if cur is None or cur.hunks > 0:
                cur = FileDiff(path=p or "", old_path=p or "")
                ordered.append(cur)
                hunk = 0
            if p is None:
                cur.status = "added"
            else:
                cur.old_path = p
        elif raw.startswith("+++ ") and cur is not None:
            p = _header_path(raw[4:], "b/")
            if p is None:
                cur.status = "deleted"
                cur.path = cur.old_path
            else:
                cur.path = p
        elif cur is not None and raw.startswith("new file mode"):
            cur.status = "added"
        elif cur is not None and raw.startswith("deleted file mode"):
            cur.status = "deleted"
        elif cur is not None and raw.startswith("rename from "):
            cur.old_path = _unquote(raw[len("rename from "):])
            cur.status = "renamed"
        elif cur is not None and raw.startswith("rename to "):
            cur.path = _unquote(raw[len("rename to "):])
            cur.status = "renamed"
        elif cur is not None and (raw.startswith("Binary files ") or raw.startswith("GIT binary patch")):
            cur.binary = True
        elif raw.startswith("@@") and cur is not None:
            m = HUNK_RE.match(raw)
            if not m:
                continue
            hunk += 1
            cur.hunks = hunk
            o_start, o_cnt, n_start, n_cnt = m.groups()
            old_rem = int(o_cnt) if o_cnt is not None else 1
            new_rem = int(n_cnt) if n_cnt is not None else 1
            old_no = int(o_start) + (1 if old_rem == 0 else 0)
            new_no = int(n_start) + (1 if new_rem == 0 else 0)

    files: dict[str, FileDiff] = {}
    for fd in ordered:
        if fd.path:
            files[fd.path] = fd
    return files
