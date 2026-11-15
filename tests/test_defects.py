import json
import shlex
import subprocess

import pytest

from aiqa.cli import main
from aiqa.defects import fingerprint as fp_module
from aiqa.defects.exceptions import SinkRefused
from aiqa.defects.fingerprint import fingerprint, normalize
from aiqa.defects.github import OPERATIONS, GitHubDefectSink, Grant, marker
from aiqa.defects.sink import Issue

REPO = "cafitac/preview-example-backend"
C1, C2 = "a" * 40, "b" * 40
FP = fingerprint("backend/notes", "assertion", 0, "expected 3 notes, saw 2")


class FakeGitHub:
    """In-memory stand-in for `gh api`: records every call, never touches the network."""

    def __init__(self):
        self.issues: list[dict[str, object]] = [
            {"number": 1, "state": "open", "body": "a pull request", "pull_request": {}}
        ]
        self.comments: dict[int, list[dict[str, str]]] = {}
        self.calls: list[tuple[str, ...]] = []
        self.push = True

    def __call__(self, args):
        self.calls.append(tuple(args))
        path = next(a for a in args if a.startswith("repos/"))
        fields = dict(
            a.split("=", 1) for a in args if "=" in a and not a.startswith("repos/")
        )
        if path == f"repos/{REPO}":
            return json.dumps({"permissions": {"push": self.push}})
        if "-X" in args and path.endswith("/issues"):
            number = len(self.issues) + 1
            assert fields["labels[]"] == "aiqa-defect"
            self.issues.append(
                {"number": number, "state": "open", "body": fields["body"]}
            )
            return json.dumps({"number": number})
        if "-X" in args:
            self.comments.setdefault(int(path.split("/")[4]), []).append(
                {"body": fields["body"]}
            )
            return "{}"
        if "/comments" in path:
            return json.dumps([self.comments.get(int(path.split("/")[4]), [])])
        assert "labels=aiqa-defect" in path and "state=all" in path
        return json.dumps([self.issues])


def sink(gh, enabled=True, repos=(REPO,), operations=OPERATIONS):
    return GitHubDefectSink(
        REPO, Grant(frozenset(repos), frozenset(operations), enabled), gh
    )


@pytest.mark.parametrize(
    "noisy, clean",
    [
        ("Order 123456  saw TWO\n\titems", "order saw two items"),
        ("at 2040-01-15T10:20:30.123Z failed", "at failed"),
        ("at 2040-01-15T10:20:30+00:00 failed", "at failed"),
        ("GET https://x.test/a?token=abc&n=1 -> 500", "get https://x.test/a -> 500"),
        ("id 3f2a9c1d77e04b5a missing", "id missing"),
        ("id 123e4567-e89b-12d3-a456-426614174000 gone", "id gone"),
        ("no rows for 2040-01-15 at 10:20:30 now", "no rows for at now"),
        ("x" * 300, "x" * 200),
    ],
)
def test_normalize(noisy, clean):
    assert normalize(noisy) == clean


def test_fingerprint_identity():
    base = ("backend/notes", "assertion", 0, "expected 3 notes, saw 2")
    assert fingerprint(*base[:3], "Expected 3 notes,  saw 2 ") == FP
    for position, other in (
        (0, "frontend/notes"),
        (1, "timeout"),
        (2, 1),
        (3, "other"),
    ):
        assert fingerprint(*(*base[:position], other, *base[position + 1 :])) != FP


def test_normalization_version_is_part_of_the_input(monkeypatch):
    monkeypatch.setattr(fp_module, "NORMALIZATION_VERSION", 2)
    assert fingerprint("backend/notes", "assertion", 0, "expected 3 notes, saw 2") != FP


def test_disabled_and_ungranted_calls_refuse_before_any_request():
    gh = FakeGitHub()
    refused = [
        lambda: sink(gh, enabled=False).find(FP),
        lambda: sink(gh, repos=("other/repo",)).create(FP, "t", "b"),
        lambda: sink(gh, operations=("list",)).create(FP, "t", "b"),
        lambda: sink(gh, operations=("create",)).comment(Issue(2, "open"), FP, C1, "t"),
    ]
    invalid = [
        lambda: sink(gh).find("not-a-fingerprint"),
        lambda: sink(gh).create("not-a-fingerprint", "t", "b"),
        lambda: GitHubDefectSink("not a repo", Grant(), gh),
    ]
    for error, calls in ((SinkRefused, refused), (ValueError, invalid)):
        for call in calls:
            with pytest.raises(error):
                call()
    assert gh.calls == []
    gh.push = False  # the label would be dropped silently and find() could never see the issue again
    with pytest.raises(SinkRefused):
        sink(gh).create(FP, "t", "b")
    assert all("-X" not in c for c in gh.calls)


def test_create_labels_and_marks_then_find_matches_open_and_closed():
    gh = FakeGitHub()
    s = sink(gh)
    assert s.find(FP) is None
    issue = s.create(FP, "title", "body")
    assert s.find(FP) == issue == Issue(2, "open")  # the pull request entry is skipped
    gh.issues[1]["state"] = "closed"
    assert s.find(FP) == Issue(2, "closed")
    assert s.find(fingerprint("backend/notes", "assertion", 1, "x")) is None


def test_caller_text_cannot_forge_a_marker():
    gh = FakeGitHub()
    s = sink(gh)
    other = fingerprint("backend/notes", "assertion", 1, "x")
    s.create(FP, "t", f"observed {marker(other)}")
    assert s.find(other) is None and s.find(FP) == Issue(2, "open")


def test_comment_is_posted_once_per_commit():
    gh = FakeGitHub()
    s = sink(gh)
    issue = s.create(FP, "t", "b")
    assert s.comment(issue, FP, C1, "seen") is True
    assert s.comment(issue, FP, C1, "seen") is False
    assert s.comment(issue, FP, C2, "seen") is True
    assert len(gh.comments[2]) == 2
    with pytest.raises(ValueError):
        s.comment(
            issue, FP, "abc1234", "t"
        )  # an abbreviated id would split one commit into two markers


def test_crash_between_create_and_link_never_creates_twice():
    gh = FakeGitHub()
    s = sink(gh)
    s.create(FP, "t", "b")  # the router crashed here, before linking the number
    again = sink(
        gh
    )  # next owner: reconcile by the consistent listing before any create
    found = again.find(FP) or again.create(FP, "t", "b")
    assert found == Issue(2, "open")
    assert [i["number"] for i in gh.issues] == [1, 2]
    assert sum(1 for c in gh.calls if "-X" in c) == 1


@pytest.mark.parametrize(
    "reply",
    [
        "not json",
        "[1]",
        "[[1]]",
        "{}",
        "[{}]",
        json.dumps([[{"number": "x", "body": marker(FP)}]]),
    ],
)
def test_unexpected_github_replies_are_an_oserror(reply):
    s = sink(lambda args: reply)
    with pytest.raises(OSError):
        s.find(FP)
    with pytest.raises(OSError):
        s.create(FP, "t", "b")


def cli(line, capsys=None):
    code = main(["defect", *shlex.split(line)])
    return (code, json.loads(capsys.readouterr().out)) if capsys and code == 0 else code


def test_cli_contract_for_the_router(capsys, monkeypatch):
    gh = FakeGitHub()
    monkeypatch.setattr("aiqa.defects.github.run_gh", gh)
    assert (
        cli(f"find --repo {REPO} --grant-repo {REPO} --fingerprint {FP}") == 3
    )  # no --enabled
    assert (
        cli(f"find --repo {REPO} --enabled --fingerprint {FP}") == 3
    )  # repository not granted
    assert gh.calls == []
    capsys.readouterr()
    g = f"--repo {REPO} --grant-repo {REPO} --enabled --fingerprint {FP}"
    obs = "--scenario backend/notes --failure-class assertion --index 0 --observed 'Expected 3 notes, saw 2'"
    assert cli(f"fingerprint {obs}", capsys) == (
        0,
        {"fingerprint": FP, "normalization": 1},
    )
    assert cli(f"find {g}", capsys) == (0, {"found": False})
    assert cli(f"create {g} --title t --body b", capsys) == (
        0,
        {"found": True, "number": 2, "state": "open"},
    )
    assert cli(f"find {g}", capsys)[1]["number"] == 2
    comment = f"comment {g} --number 2 --commit {C1} --text seen"
    assert [cli(comment, capsys)[1], cli(comment, capsys)[1]] == [
        {"posted": True},
        {"posted": False},
    ]
    assert cli(f"find {g.replace(FP, 'nope')}") == 2  # invalid input
    assert (
        cli("fingerprint --scenario '' --failure-class c --index 0 --observed o") == 2
    )
    monkeypatch.setattr(
        "aiqa.defects.github.run_gh",
        lambda args: (_ for _ in ()).throw(subprocess.TimeoutExpired("gh", 60)),
    )
    assert cli(f"find {g}") == 4  # the call failed
