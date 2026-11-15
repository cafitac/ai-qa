from __future__ import annotations

import re
import subprocess
from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, cast

from ..contracts import InvalidInput, parse_json
from .exceptions import SinkRefused
from .sink import Issue

LABEL = "aiqa-defect"
OPERATIONS = frozenset({"list", "create", "comment"})
_REPO = re.compile(r"[\w.-]+/[\w.-]+")
_FP = re.compile(r"[0-9a-f]{64}")
_COMMIT = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
Runner = Callable[[Sequence[str]], str]


@dataclass(frozen=True)
class Grant:
    """Named repositories and operations; off by default (`sink.github.enabled`). Ungranted calls refuse before any request."""

    repos: frozenset[str] = frozenset()
    operations: frozenset[str] = OPERATIONS
    enabled: bool = False


def run_gh(args: Sequence[str]) -> str:
    done = subprocess.run(
        ["gh", "api", *args],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=60,
        check=True,
    )
    return done.stdout


def _check(pattern: re.Pattern[str], value: str, message: str) -> None:
    if not pattern.fullmatch(value):
        raise ValueError(
            message
        )  # invalid input, not a refusal: the CLI exits 2, not 3


def _json(text: str) -> Any:
    try:
        return parse_json(text)
    except InvalidInput:
        raise OSError("unexpected GitHub response") from None


@contextmanager
def _reply() -> Generator[None]:
    try:
        yield
    except (KeyError, TypeError, ValueError):
        raise OSError("unexpected GitHub response") from None


def _plain(text: str) -> str:
    return text.replace(
        "<!--", "&lt;!--"
    )  # caller text must not be able to forge a marker


def marker(fingerprint: str) -> str:
    _check(_FP, fingerprint, "fingerprint must be 64 lowercase hex characters")
    return f"<!-- aiqa-fp:{fingerprint} -->"


def occurrence_marker(fingerprint: str, commit: str) -> str:
    _check(_FP, fingerprint, "fingerprint must be 64 lowercase hex characters")
    _check(
        _COMMIT, commit, "commit must be the full 40 or 64 character lowercase hex id"
    )
    return f"<!-- aiqa-occ:{fingerprint}:{commit} -->"


class GitHubDefectSink:
    def __init__(self, repo: str, grant: Grant, runner: Runner | None = None):
        _check(_REPO, repo, "repository must be owner/name")
        self.repo, self.grant, self.runner = repo, grant, runner or run_gh

    def _authorize(self, operation: str) -> None:
        if not self.grant.enabled:
            raise SinkRefused("sink.github.enabled is off")
        if self.repo not in self.grant.repos or operation not in self.grant.operations:
            raise SinkRefused(f"{operation} on {self.repo} is not granted")

    def _call(self, operation: str, *args: str) -> str:
        self._authorize(operation)
        return self.runner(args)

    def _pages(self, operation: str, path: str) -> list[dict[str, Any]]:
        # Listing is consistent (search is not): the issues endpoint, every page.
        out = self._call(operation, "--paginate", "--slurp", path)
        raw = _json(out)
        pages = cast("list[Any]", raw) if isinstance(raw, list) else [None]
        if not all(isinstance(p, list) for p in pages):
            raise OSError("unexpected GitHub response")
        items = [item for page in cast("list[list[Any]]", pages) for item in page]
        if not all(isinstance(item, dict) for item in items):
            raise OSError("unexpected GitHub response")
        return cast("list[dict[str, Any]]", items)

    def find(self, fingerprint: str) -> Issue | None:
        mark = marker(fingerprint)
        path = f"repos/{self.repo}/issues?labels={LABEL}&state=all&per_page=100"
        with _reply():
            for item in self._pages("list", path):
                if "pull_request" not in item and mark in str(item.get("body")):
                    return Issue(int(str(item["number"])), str(item["state"]))
        return None

    def create(self, fingerprint: str, title: str, body: str) -> Issue:
        mark = marker(fingerprint)
        self._authorize("create")
        # Without push access GitHub drops the label silently and find() could never see the issue again.
        with _reply():
            pushable = _json(self._call("list", f"repos/{self.repo}"))["permissions"][
                "push"
            ]
        if not pushable:
            raise SinkRefused(
                "the token has no push access: the label would not be applied"
            )
        out = self._call(
            "create",
            "-X", "POST", f"repos/{self.repo}/issues",
            "-f", f"title={title}",
            "-f", f"body={_plain(body)}\n\n{mark}",
            "-f", f"labels[]={LABEL}",
        )  # fmt: skip
        with _reply():
            return Issue(int(_json(out)["number"]), "open")

    def comment(self, issue: Issue, fingerprint: str, commit: str, text: str) -> bool:
        mark = occurrence_marker(fingerprint, commit)
        self._authorize(
            "comment"
        )  # before the preliminary read: an ungranted call sends nothing
        path = f"repos/{self.repo}/issues/{issue.number}/comments?per_page=100"
        if any(mark in str(c.get("body")) for c in self._pages("list", path)):
            return False
        self._call(
            "comment",
            "-X", "POST", f"repos/{self.repo}/issues/{issue.number}/comments",
            "-f", f"body={_plain(text)}\n\n{mark}",
        )  # fmt: skip
        return True
