from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Issue:
    number: int
    state: str  # "open" | "closed"


class DefectSink(Protocol):
    def find(self, fingerprint: str) -> Issue | None: ...

    def create(self, fingerprint: str, title: str, body: str) -> Issue: ...

    # True if posted, False if this commit already has its occurrence comment
    def comment(
        self, issue: Issue, fingerprint: str, commit: str, text: str
    ) -> bool: ...
