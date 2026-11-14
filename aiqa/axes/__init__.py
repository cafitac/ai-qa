from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ..contracts import InvalidInput

API_VERSION = "ai-qa/axes/v1"


@dataclass(frozen=True)
class Cell:
    """An observed matrix cell: what the code does, never what it should do.

    `key` is stable across runs; `id`, `req`, `scope` and `risk` are assigned
    when a cell enters a QA design (the `MatrixCell` shape of qa-design/1).
    """

    key: str
    axis: str
    kind: str
    subject: str
    file: str
    line: int
    detail: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "key": self.key,
            "axis": self.axis,
            "platform": "web",
            "source": "observed",
            "kind": self.kind,
            "subject": self.subject,
            "file": self.file,
            "line": self.line,
        }
        if self.detail:
            out["detail"] = self.detail
        return out


class AxisExtractor(Protocol):
    """Stack-specific static extractor; `extract` returns None for an unsupported stack."""

    name: str

    def extract(self, repo: Path) -> list[Cell] | None: ...


def extract_axes(
    repo: Path, extractors: tuple[AxisExtractor, ...] | None = None
) -> dict[str, Any]:
    """`axes: observed` with cells, or `axes: unknown` when no extractor supports the stack."""
    if not repo.is_dir():
        raise InvalidInput(f"Not a directory: {repo}")
    if extractors is None:
        from .fastapi_extractor import FastApiExtractor

        extractors = (FastApiExtractor(),)
    for extractor in extractors:
        cells = extractor.extract(repo)
        if cells is not None:
            return {
                "apiVersion": API_VERSION,
                "axes": "observed",
                "extractor": extractor.name,
                "cells": [c.as_dict() for c in cells],
            }
    return {
        "apiVersion": API_VERSION,
        "axes": "unknown",
        "extractor": None,
        "cells": [],
    }
