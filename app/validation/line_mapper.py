"""Map finding line ranges onto lines GitHub will accept for inline comments."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.github.diff_parser import FileDiff


@dataclass(frozen=True)
class InlineComment:
    path: str
    line: int
    start_line: Optional[int] = None
    side: str = "RIGHT"

    def to_api(self, body: str) -> dict:
        data: dict = {"path": self.path, "body": body, "line": self.line, "side": self.side}
        if self.start_line is not None and self.start_line < self.line:
            data["start_line"] = self.start_line
            data["start_side"] = self.side
        return data


def map_to_inline(path: str, start: int, end: int, files: dict[str, FileDiff]) -> Optional[InlineComment]:
    fd = files.get(path)
    if fd is None or fd.binary or fd.status == "deleted" or end < start:
        return None
    visible = fd.visible
    span = range(start, end + 1)
    if all(n in visible for n in span) and len({visible[n].hunk for n in span}) == 1:
        return InlineComment(path, end, start if start < end else None)
    for n in span:
        if n in fd.added:
            return InlineComment(path, n)
    for n in span:
        if n in visible:
            return InlineComment(path, n)
    return None
