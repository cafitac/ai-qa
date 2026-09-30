from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import urljoin

from .clock import default_clock
from .contracts import Config, InvalidInput, Scenario, duration, url_origin, validate
from .ports import (
    AgentContext,
    AgentOutput,
    AgentRunner,
    BrowserSession,
    DescriptorSource,
    ScenarioSource,
    VerdictGate,
)
from .run import Budget, Evidence, Run, ScenarioResult
from .storage import RunStorage, atomic_write, write_json


class BoundaryError(RuntimeError):
    def __init__(self, boundary: str, cause: OSError | ValueError):
        self.boundary = boundary
        self.reason = type(cause).__name__


def boundary_call[T](boundary: str, call: Callable[[], T]) -> T:
    try:
        return call()
    except Refused as exc:
        if exc.reason not in (
            "environment_not_ready",
            "login_required",
            "invalid_descriptor",
            "invalid_scenarios",
            "no_scenarios",
        ):
            raise BoundaryError(boundary, ValueError("Invalid refusal reason")) from exc
        raise
    except OSError as exc:
        raise BoundaryError(boundary, exc) from exc


class Refused(RuntimeError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def agent_text(value: object) -> str:
    if not isinstance(value, str) or len(value) > 500:
        raise ValueError("Invalid agent text")
    value.encode("utf-8")
    if any((ord(c) < 32 and c not in "\n\t") or 127 <= ord(c) <= 159 for c in value):
        raise ValueError("Invalid agent text")
    return value


def evidence_uri(
    uri: object,
    run_dir: Path,
    scenario_dir: Path,
    kind: str = "log",
    origins: tuple[str, ...] = (),
) -> str:
    """Validate evidence against the current attempt and allowed HTTP origins."""
    if kind == "http":
        if not isinstance(uri, str) or url_origin(uri) not in origins:
            raise ValueError("Invalid HTTP evidence")
        return uri
    if kind not in ("screenshot", "log"):
        raise ValueError("Invalid evidence type")
    if (
        not isinstance(uri, str)
        or not 1 <= len(uri) <= 4096
        or any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in uri)
        or "\\" in uri
        or Path(uri).is_absolute()
        or ".." in uri.split("/")
    ):
        raise ValueError("Invalid evidence URI")
    uri.encode("utf-8")
    try:
        (run_dir / uri).resolve().relative_to(scenario_dir.resolve())
    except (ValueError, RuntimeError) as exc:
        raise ValueError("Evidence outside scenario directory") from exc
    if not (run_dir / uri).is_file():
        raise ValueError("Evidence is not a regular file")
    return uri


class JsonVerdictGate:
    """QU1 placeholder: JSON status only; QU2 supplies evidence and security gates."""

    def accept(
        self,
        scenario: Scenario,
        output: AgentOutput,
        transcript: Path | None,
        files: tuple[Path, ...],
        caps: AgentContext,
    ) -> ScenarioResult:
        try:
            raw: object = json.loads(output.result_text)
            if not isinstance(raw, dict):
                raise TypeError("Invalid result")
            value = cast(dict[str, Any], raw)
            if value.get("status") not in (
                "PASSED",
                "FAILED",
            ):
                raise ValueError("Invalid status")
            summary = value.get("summary", "")
            checks = value.get("checks", [])
            if (
                not isinstance(summary, str)
                or len(summary) > 500
                or not isinstance(checks, list)
            ):
                raise ValueError("Invalid result")
            agent_text(summary)
            for check in cast(list[object], checks):
                if not isinstance(check, dict):
                    raise TypeError("Invalid check")
                check_data = cast(dict[str, object], check)
                agent_text(check_data.get("expect"))
                agent_text(check_data.get("observed"))
            result = ScenarioResult(
                scenario.qualified_id,
                value["status"],
                summary,
                checks=tuple(cast(list[dict[str, Any]], checks)),
                turns=output.turns,
                seconds=output.seconds,
            )
            result.as_dict()
            return result
        except (ValueError, TypeError, RecursionError):
            return ScenarioResult(
                scenario.qualified_id,
                "FAILED",
                "agent_protocol",
                "agent_protocol",
                turns=output.turns,
                seconds=output.seconds,
            )


def report(run: Run) -> dict[str, object]:
    return validate(
        "qa-report",
        {
            "apiVersion": "preview-hub/v1",
            "kind": "QaReport",
            "environment": run.environment,
            "commits": dict(run.commits),
            "startedAt": run.started_at,
            "finishedAt": run.finished_at or run.clock().isoformat(),
            "scenarios": [
                {
                    "id": r.scenario_id,
                    "status": r.status,
                    "summary": r.summary,
                    "evidence": [{"type": e.type, "uri": e.uri} for e in r.evidence],
                }
                for r in run.results
            ],
            "summary": {
                status.lower(): sum(r.status == status for r in run.results)
                for status in ("PASSED", "FAILED", "SKIPPED")
            },
        },
    )


def summary(run: Run | dict[str, Any]) -> str:
    data = run.as_dict() if isinstance(run, Run) else run
    lines = [
        f"# {data['id']}",
        "",
        f"State: {data['state']}",
        "",
        "| Scenario | Status | Summary |",
        "| --- | --- | --- |",
    ]
    for r in data["results"]:
        text = r["summary"].replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {r['scenario_id']} | {r['status']} | {text} |")
    if data["refusal_reason"]:
        lines += ["", data["refusal_reason"]]
    if data.get("abort_reason"):
        lines += ["", f"aborted: {data['abort_reason']}"]
    return "\n".join(lines) + "\n"


class RunScenarios:
    def __init__(
        self,
        descriptor_source: DescriptorSource,
        scenario_source: ScenarioSource,
        agent_runner: AgentRunner,
        config: Config,
        browser_session: BrowserSession | None = None,
        verdict_gate: VerdictGate | None = None,
        agent_kind: str | None = None,
        clock: Callable[[], datetime] = default_clock,
    ):
        self.clock = clock
        self.descriptor_source = descriptor_source
        self.scenario_source = scenario_source
        self.agent_runner = agent_runner
        self.config = config
        self.browser_session = browser_session
        self.verdict_gate = verdict_gate or JsonVerdictGate()
        self.agent_kind = agent_kind or config.agent_kind
        self.storage = RunStorage(config.runs_dir)
        self.last_run: Run | None = None
        self.persisted_run: dict[str, Any] | None = None

    def execute(
        self, environment: str, tags: tuple[str, ...] = (), only: tuple[str, ...] = ()
    ) -> int:
        try:
            return self._execute(environment, tags, only)
        except BoundaryError as exc:
            print(f"{exc.boundary} error: aborted: {exc.reason}")
            self._recover_aborted(f"{exc.boundary}: {exc.reason}")
            return 4
        except InvalidInput as exc:
            if self.last_run is None:
                raise
            self._recover_aborted(type(exc).__name__)
            return 4
        except OSError as exc:
            print("Run storage error: cannot read or write run artifacts")
            self._recover_aborted(type(exc).__name__)
            return 4
        except (KeyboardInterrupt, Exception) as exc:  # noqa: BLE001 - handler recovery boundary
            reason = (
                "interrupted"
                if isinstance(exc, KeyboardInterrupt)
                else type(exc).__name__
            )
            self._recover_aborted(reason)
            return 4

    def _recover_aborted(self, reason: str) -> None:
        run = self.last_run
        if run is None:
            return
        run.abort_reason = reason
        if run.state in ("PREFLIGHT", "RUNNING"):
            run.transition("ABORTED")
        path = self.storage.root / run.id
        # Remove any completion claim before attempting best-effort recovery.
        for name in ("summary.md", "report.json"):
            try:
                (path / name).unlink(missing_ok=True)
            except OSError:
                pass
        try:
            saved = validate(
                "run", json.loads((path / "run.json").read_text(encoding="utf-8"))
            )
        except (OSError, ValueError, RecursionError):
            return
        saved["state"] = "ABORTED"
        saved["abort_reason"] = reason
        saved["finished_at"] = self.clock().isoformat()
        try:
            write_json(path / "run.json", saved)
        except (OSError, InvalidInput):
            # Use the state that is actually on disk, not the failed candidate.
            try:
                saved = validate(
                    "run", json.loads((path / "run.json").read_text(encoding="utf-8"))
                )
            except (OSError, ValueError, RecursionError):
                return
        self.persisted_run = self.storage.load(run.id)
        saved = self.persisted_run
        try:
            atomic_write(
                path / "summary.md",
                summary(saved),
            )
        except OSError:
            pass

    def _execute(
        self, environment: str, tags: tuple[str, ...], only: tuple[str, ...]
    ) -> int:
        at = self.clock()
        path = self.storage.create(environment, at)
        cfg = self.config
        budget = Budget(
            cfg.max_scenarios, cfg.max_turns, cfg.scenario_timeout, cfg.protocol_retries
        )
        run = Run(
            path.name,
            environment,
            budget,
            self.agent_kind,
            cfg.agent_model,
            started_at=at.isoformat(),
            clock=self.clock,
        )
        self.last_run = run
        self.storage.save(run)
        run.transition("PREFLIGHT")
        self.storage.save(run)
        input_reason = "invalid_descriptor"
        state: Path | None = None
        browser = self.browser_session
        try:
            if browser:
                state = boundary_call(
                    "Browser", lambda: browser.preflight(cfg.dashboard_url)
                )
            input_reason = "invalid_descriptor"
            descriptor = boundary_call(
                "Source", lambda: self.descriptor_source.get(environment)
            )
            if (
                descriptor is None
                or descriptor.data["name"] != environment
                or not descriptor.is_ready(self.clock())
            ):
                raise Refused("environment_not_ready")
            origins = descriptor.origins()
            entry = descriptor.data["entryUrl"]
            if not entry or not origins:
                raise Refused("environment_not_ready")
            input_reason = "invalid_scenarios"
            scenarios: list[Scenario] = []
            try:
                for service in descriptor.data["services"]:
                    scenarios.extend(
                        boundary_call(
                            "Source",
                            lambda service=service: self.scenario_source.load(
                                service["name"],
                                service["repo"],
                                service["commit"],
                                duration(budget.scenario_timeout),
                            ),
                        )
                    )
                start_urls = {
                    s.qualified_id: urljoin(entry, s.start) for s in scenarios
                }
                if any(url_origin(url) not in origins for url in start_urls.values()):
                    raise InvalidInput("Scenario start is outside allowed origins")
                ids = [s.qualified_id for s in scenarios]
                if len(ids) != len(set(ids)):
                    raise InvalidInput("Duplicate scenario identity")
                if any(item not in ids for item in only):
                    raise InvalidInput("Unknown --only scenario")
            except InvalidInput:
                raise Refused("invalid_scenarios") from None
            scenarios = [
                s
                for s in scenarios
                if (not tags or set(tags).intersection(s.tags))
                and (not only or s.qualified_id in only)
            ]
            if not scenarios:
                raise Refused("no_scenarios")
            if browser:
                state = boundary_call("Browser", lambda: browser.preflight(entry))
            run.start(descriptor.commits(), [s.qualified_id for s in scenarios])
            self.storage.save(run)
            retries = budget.protocol_retries
            agent_calls = 0
            for index, scenario in enumerate(scenarios):
                folder = path / "scenarios" / scenario.qualified_id.replace("/", "__")
                folder.mkdir()
                if index >= budget.max_scenarios:
                    result = ScenarioResult(
                        scenario.qualified_id,
                        "SKIPPED",
                        "Run scenario budget exhausted",
                    )
                else:
                    try:
                        caps = AgentContext(
                            folder,
                            start_urls[scenario.qualified_id],
                            tuple(
                                sorted(
                                    set(origins)
                                    | {url_origin(f"https://{cfg.access_team_domain}")}
                                )
                            ),
                            budget.max_turns,
                            duration(scenario.timeout or budget.scenario_timeout),
                            cfg.agent_model,
                            state,
                        )
                        attempt = 0
                        while True:
                            attempt += 1
                            output_dir = folder / f"attempt-{attempt}"
                            output_dir.mkdir()
                            caps = replace(caps, output_dir=output_dir)
                            if agent_calls >= budget.max_agent_calls:
                                raise RuntimeError("Agent call budget exhausted")
                            agent_calls += 1
                            output = boundary_call(
                                "Agent",
                                lambda scenario=scenario, caps=caps: (
                                    self.agent_runner.run(scenario, caps)
                                ),
                            )
                            try:
                                if output.transcript_path is not None:
                                    evidence_uri(
                                        output.transcript_path.relative_to(
                                            path
                                        ).as_posix(),
                                        path,
                                        output_dir,
                                    )
                                valid_transcript = True
                            except (
                                ValueError,
                                TypeError,
                                AttributeError,
                                RuntimeError,
                            ):
                                valid_transcript = False
                            if (
                                not valid_transcript
                                or type(output.turns) is not int
                                or not 0 <= output.turns <= 2**63 - 1
                                or type(output.seconds) not in (int, float)
                                or not 0 <= output.seconds <= 2**63 - 1
                                or not math.isfinite(output.seconds)
                                or type(output.exit_code) is not int
                                or type(output.timed_out) is not bool
                                or (
                                    output.transcript_path is not None
                                    and (
                                        not isinstance(
                                            cast(object, output.transcript_path), Path
                                        )
                                        or any(
                                            0xD800 <= ord(c) <= 0xDFFF
                                            for c in str(output.transcript_path)
                                        )
                                    )
                                )
                            ):
                                output = AgentOutput(
                                    "",
                                    output.transcript_path
                                    if isinstance(
                                        cast(object, output.transcript_path), Path
                                    )
                                    else None,
                                )
                                result = ScenarioResult(
                                    scenario.qualified_id,
                                    "FAILED",
                                    "agent_protocol",
                                    "agent_protocol",
                                )
                            else:
                                reason = (
                                    "timeout"
                                    if output.timed_out
                                    or output.seconds > caps.timeout_seconds
                                    else "turn_cap"
                                    if output.turns > caps.max_turns
                                    else "agent_error"
                                    if output.exit_code
                                    else None
                                )
                                if reason:
                                    result = ScenarioResult(
                                        scenario.qualified_id,
                                        "FAILED",
                                        reason,
                                        reason,
                                        turns=output.turns,
                                        seconds=output.seconds,
                                    )
                                else:
                                    files = tuple(output_dir.iterdir())
                                    try:
                                        result = self.verdict_gate.accept(
                                            scenario,
                                            output,
                                            output.transcript_path,
                                            files,
                                            caps,
                                        )
                                        result.as_dict()
                                        if result.scenario_id != scenario.qualified_id:
                                            raise ValueError(
                                                "Invalid scenario identity"
                                            )
                                        agent_text(result.summary)
                                        for item in result.evidence:
                                            evidence_uri(
                                                item.uri,
                                                path,
                                                output_dir,
                                                item.type,
                                                caps.allowed_origins,
                                            )
                                        for check in result.checks:
                                            agent_text(check["expect"])
                                            agent_text(check["observed"])
                                    except OSError:
                                        raise
                                    except Exception:  # noqa: BLE001 - agent interpretation boundary
                                        result = ScenarioResult(
                                            scenario.qualified_id,
                                            "FAILED",
                                            "agent_protocol",
                                            "agent_protocol",
                                            turns=output.turns,
                                            seconds=output.seconds,
                                        )
                            if result.reason == "agent_protocol" and retries:
                                retries -= 1
                                continue
                            evidence = list(result.evidence)
                            candidates = [
                                (f, "screenshot") for f in output_dir.glob("*.png")
                            ]
                            if output.transcript_path is not None:
                                candidates.append((output.transcript_path, "log"))
                            for file, kind in candidates:
                                try:
                                    uri = evidence_uri(
                                        file.relative_to(path).as_posix(),
                                        path,
                                        output_dir,
                                    )
                                except (
                                    ValueError,
                                    UnicodeError,
                                    RuntimeError,
                                ):
                                    continue
                                if Evidence(kind, uri) not in evidence:
                                    evidence.append(Evidence(kind, uri))
                            result = ScenarioResult(
                                result.scenario_id,
                                result.status,
                                result.summary,
                                result.reason,
                                result.checks,
                                tuple(evidence),
                                result.turns,
                                result.seconds,
                            )
                            break
                    except OSError:
                        result = ScenarioResult(
                            scenario.qualified_id,
                            "FAILED",
                            "agent_error",
                            "agent_error",
                        )
                run.record(result)
                write_json(folder / "result.json", result.as_dict())
                self.storage.save(run)
            payload = report(run)
            run.transition("COMPLETED", finished_at=str(payload["finishedAt"]))
            self.storage.save(run)
            write_json(path / "report.json", payload)
            atomic_write(path / "summary.md", summary(run))
            return int(any(r.status == "FAILED" for r in run.results))
        except Refused as exc:
            if run.state != "PREFLIGHT":
                run.transition("ABORTED")
                self.storage.save(run)
                atomic_write(path / "summary.md", summary(run))
                return 4
            run.refusal_reason = exc.reason
            run.transition("REFUSED")
            self.storage.save(run)
            atomic_write(path / "summary.md", summary(run))
            return 2 if exc.reason in ("invalid_scenarios", "invalid_descriptor") else 3
        except InvalidInput as exc:
            if run.state == "PREFLIGHT":
                run.refusal_reason = input_reason
                run.transition("REFUSED")
                self.storage.save(run)
                atomic_write(path / "summary.md", summary(run))
                return 2
            run.abort_reason = type(exc).__name__
            print(f"aborted: {run.abort_reason}")
            run.transition("ABORTED")
            (path / "report.json").unlink(missing_ok=True)
            self.storage.save(run)
            atomic_write(path / "summary.md", summary(run))
            return 4
        except OSError:
            raise
        except BoundaryError:
            raise
        except (KeyboardInterrupt, Exception) as exc:  # noqa: BLE001 - run abort boundary
            # Preserve partial results without exposing arbitrary exception text.
            reason = (
                "interrupted"
                if isinstance(exc, KeyboardInterrupt)
                else type(exc).__name__
            )
            print(f"aborted: {reason}")
            self._recover_aborted(reason)
            return 4
