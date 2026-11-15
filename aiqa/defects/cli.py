from __future__ import annotations

import argparse
import json
import subprocess
from typing import Any

from .exceptions import SinkRefused
from .fingerprint import NORMALIZATION_VERSION, fingerprint
from .github import GitHubDefectSink, Grant
from .sink import DefectSink, Issue


def add_arguments(commands: Any) -> None:
    sub = commands.add_parser("defect").add_subparsers(
        dest="defect_command", required=True
    )
    fp = sub.add_parser("fingerprint")
    fp.add_argument("--scenario", required=True)
    fp.add_argument("--failure-class", required=True)
    fp.add_argument("--index", type=int, required=True)
    fp.add_argument("--observed", required=True)
    for name in ("find", "create", "comment"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--repo", required=True)
        cmd.add_argument("--grant-repo", action="append", default=[])
        cmd.add_argument("--enabled", action="store_true")
        cmd.add_argument("--fingerprint", required=True)
    sub.choices["create"].add_argument("--title", required=True)
    sub.choices["create"].add_argument("--body", required=True)
    sub.choices["comment"].add_argument("--number", type=int, required=True)
    sub.choices["comment"].add_argument("--commit", required=True)
    sub.choices["comment"].add_argument("--text", required=True)


def run(args: argparse.Namespace) -> int:
    try:
        if args.defect_command == "fingerprint":
            out: dict[str, object] = {
                "fingerprint": fingerprint(
                    args.scenario, args.failure_class, args.index, args.observed
                ),
                "normalization": NORMALIZATION_VERSION,
            }
        else:
            sink: DefectSink = GitHubDefectSink(
                args.repo, Grant(frozenset(args.grant_repo), enabled=args.enabled)
            )
            if args.defect_command == "find":
                found = sink.find(args.fingerprint)
                out = {"found": found is not None, **(found.__dict__ if found else {})}
            elif args.defect_command == "create":
                out = {
                    "found": True,
                    **sink.create(args.fingerprint, args.title, args.body).__dict__,
                }
            else:
                posted = sink.comment(
                    Issue(args.number, "open"), args.fingerprint, args.commit, args.text
                )
                out = {"posted": posted}
    except ValueError as exc:
        print(str(exc))
        return 2
    except SinkRefused as exc:
        print(f"refused: {exc}")
        return 3
    except (OSError, subprocess.SubprocessError) as exc:
        detail = getattr(exc, "stderr", None) or ""
        print(
            f"GitHub call failed: {type(exc).__name__} {detail.strip()[:200]}".strip()
        )
        return 4
    print(json.dumps(out))
    return 0
