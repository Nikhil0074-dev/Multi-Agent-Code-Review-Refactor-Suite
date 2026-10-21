"""Test helpers: build unified diffs from old/new text."""
from __future__ import annotations

import difflib


def make_diff(path: str, old: str, new: str, n: int = 3) -> str:
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    header = f"diff --git a/{path} b/{path}\n"
    if not old:
        header += "new file mode 100644\n"
        fromfile = "/dev/null"
    else:
        fromfile = f"a/{path}"
    body = "".join(difflib.unified_diff(old_lines, new_lines, fromfile=fromfile, tofile=f"b/{path}", n=n))
    return header + body
