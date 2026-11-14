from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from . import mutants
from .browser import BrowserFailure
from .clock import default_clock
from .contracts import Config, InvalidInput
from .fakes import FakeAgentRunner, FileDescriptorSource, FileScenarioSource
from .storage import RunStorage
from .usecases import Refused, RunScenarios, exit_code


def main(
    argv: list[str] | None = None,
    *,
    clock: Callable[[], datetime] = default_clock,
) -> int:
    """Run the CLI; callers may inject a clock for deterministic tests."""
    parser = argparse.ArgumentParser(prog="aiqa")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("environment")
    run.add_argument("--tag", action="append", default=[])
    run.add_argument("--only", action="append", default=[])
    run.add_argument("--descriptor", type=Path)
    run.add_argument("--scenarios", type=Path)
    run.add_argument(
        "--agent",
        choices=["fake", "claude", "codex"],
        help="fake is development-only: no browser or real agent",
    )
    run.add_argument("--config", type=Path)
    run.add_argument("--access", choices=["session", "service-token"])
    run.add_argument("--run-id-file", type=Path)
    prune = commands.add_parser("prune")
    prune.add_argument("--keep", type=int, required=True)
    prune.add_argument("--config", type=Path)
    show = commands.add_parser("show")
    show.add_argument("run_id", nargs="?")
    show.add_argument("--config", type=Path)
    for name in ("login", "doctor"):
        command = commands.add_parser(name)
        command.add_argument("--config", type=Path)
    commands.choices["doctor"].add_argument(
        "--access", choices=["session", "service-token"]
    )
    design = commands.add_parser("design").add_subparsers(
        dest="design_command", required=True
    )
    gate = design.add_parser("check")
    gate.add_argument("--spec", type=Path, required=True)
    gate.add_argument("--design", type=Path, required=True)
    gate.add_argument("--scenarios", type=Path)
    gate.add_argument("--format", choices=["json", "text"], default="json")
    axes = commands.add_parser("axes")
    axes.add_argument("repo", type=Path)
    mutants.add_arguments(commands)
    args = parser.parse_args(argv)
    try:
        if args.command == "mutant":
            return mutants.run(args, clock)
        if args.command == "axes":
            from .axes import extract_axes

            print(json.dumps(extract_axes(args.repo)))
            return 0
        if args.command == "design":
            from .design import run_check

            return run_check(args.spec, args.design, args.scenarios, args.format)
        config = Config.load(args.config)
        if args.command == "prune":
            storage = RunStorage(config.runs_dir)
            for removed in storage.prune(args.keep):
                print(f"removed: {removed}")
            for skipped in storage.prune_skipped:
                print(f"skipped: {skipped}")
            return 0
        if args.command in ("run", "doctor") and args.access:
            config = replace(config, access_mode=args.access.replace("-", "_"))
        if args.command == "login":
            from .browser import PlaywrightSession

            PlaywrightSession(config).login()
            return 0
        if args.command == "doctor":
            from .doctor import doctor

            return doctor(config)
        if args.command == "show":
            data = RunStorage(config.runs_dir).load(args.run_id, check_liveness=True)
            print(f"{data['id']}: {data['state']}")
            for result in data["results"]:
                print(
                    f"{result['scenario_id']}: {result['status']} — {result['summary']}"
                )
            if data.get("abort_reason"):
                print(f"aborted: {data['abort_reason']}")
            if data["refusal_reason"]:
                print(data["refusal_reason"])
            if data["state"] == "COMPLETED":
                return exit_code(r["status"] for r in data["results"])
            if data["state"] == "REFUSED":
                return (
                    2
                    if data["refusal_reason"]
                    in ("invalid_scenarios", "invalid_descriptor")
                    else 3
                )
            return 4 if data["state"] in ("ABORTED", "INTERRUPTED") else 5
        agent = args.agent or config.agent_kind
        from .agents.claude import ClaudeCodeRunner
        from .agents.codex import CodexRunner
        from .browser import PlaywrightSession
        from .sources import GitHubRawScenarioSource, HubDescriptorSource

        if agent == "fake" and (args.descriptor is None or args.scenarios is None):
            raise InvalidInput("--agent fake requires --descriptor and --scenarios")
        if agent != "fake":
            from .doctor import dependency_errors

            errors = dependency_errors(config, agent)
            if errors:
                raise InvalidInput("; ".join(errors))
        from .browser import ServiceTokenPreflight

        if config.access_mode == "service_token" and args.descriptor is None:
            raise InvalidInput("Service-token mode requires --descriptor")
        browser = (
            (
                ServiceTokenPreflight(config)
                if config.access_mode == "service_token"
                else PlaywrightSession(config)
            )
            if agent != "fake"
            else None
        )
        if args.descriptor:
            descriptor_source = FileDescriptorSource(args.descriptor)
        else:
            assert browser is not None
            descriptor_source = HubDescriptorSource(browser)
        usecase = RunScenarios(
            descriptor_source,
            FileScenarioSource(args.scenarios)
            if args.scenarios
            else GitHubRawScenarioSource(),
            FakeAgentRunner()
            if agent == "fake"
            else CodexRunner(config)
            if agent == "codex"
            else ClaudeCodeRunner(config),
            config,
            browser_session=browser,
            agent_kind=agent,
            clock=clock,
            run_id_file=args.run_id_file,
        )
        code = usecase.execute(args.environment, tuple(args.tag), tuple(args.only))
        if usecase.last_run:
            data = usecase.persisted_run or usecase.last_run.as_dict()
            print(f"{data['id']}: {data['state']}")
            if data.get("abort_reason"):
                print(f"aborted: {data['abort_reason']}")
            if data["refusal_reason"]:
                print(data["refusal_reason"])
        return code
    except BrowserFailure as exc:
        print(str(exc))
        return 4
    except Refused as exc:
        print(str(exc))
        return 3
    except ImportError:
        print("Playwright is not installed; install the declared dependencies")
        return 2
    except OSError:
        print("Storage error: cannot read or write run artifacts")
        return 4
    except InvalidInput as exc:
        print(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
