from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any

from .clock import default_clock
from .contracts import InvalidInput, duration, validate


@dataclass(frozen=True)
class Budget:
    max_scenarios: int = 20
    max_turns: int = 25
    scenario_timeout: str = "300s"
    protocol_retries: int = 1

    def __post_init__(self) -> None:
        if (
            self.max_scenarios < 1
            or self.max_turns < 1
            or self.protocol_retries not in (0, 1)
        ):
            raise InvalidInput("Invalid budget")
        duration(self.scenario_timeout)

    @property
    def max_agent_calls(self) -> int:
        return self.max_scenarios + self.protocol_retries


@dataclass(frozen=True)
class Evidence:
    type: str
    uri: str


@dataclass(frozen=True)
class ScenarioResult:
    scenario_id: str
    status: str
    summary: str
    reason: str | None = None
    checks: tuple[dict[str, Any], ...] = ()
    evidence: tuple[Evidence, ...] = ()
    turns: int = 0
    seconds: float = 0

    def as_dict(self) -> dict[str, Any]:
        data = {"apiVersion": "ai-qa/v1", **asdict(self)}
        data["checks"] = list(data["checks"])
        data["evidence"] = list(data["evidence"])
        return validate("scenario-result", data)


@dataclass
class Run:
    id: str
    environment: str
    budget: Budget
    agent_kind: str
    agent_model: str | None = None
    pid: int = field(default_factory=os.getpid)
    started_at: str = ""
    clock: Callable[[], datetime] = field(default=default_clock, repr=False)
    finished_at: str | None = None
    refusal_reason: str | None = None
    abort_reason: str | None = None
    _state: str = field(default="CREATED", init=False)
    _commits: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType({}), init=False
    )
    _results: list[ScenarioResult] = field(
        default_factory=list[ScenarioResult], init=False
    )
    _scenario_ids: frozenset[str] = field(default_factory=frozenset[str], init=False)

    def __post_init__(self) -> None:
        if not self.started_at:
            self.started_at = self.clock().isoformat()

    @property
    def state(self) -> str:
        return self._state

    @property
    def commits(self) -> Mapping[str, str]:
        return self._commits

    @property
    def results(self) -> tuple[ScenarioResult, ...]:
        return tuple(self._results)

    def start(self, commits: Mapping[str, str], scenario_ids: list[str]) -> None:
        if self.state != "PREFLIGHT" or len(scenario_ids) != len(set(scenario_ids)):
            raise ValueError("Cannot start run")
        self._commits = MappingProxyType(dict(commits))
        self._scenario_ids = frozenset(scenario_ids)
        self.transition("RUNNING")

    def transition(self, state: str, *, finished_at: str | None = None) -> None:
        allowed = {
            "CREATED": {"PREFLIGHT"},
            "PREFLIGHT": {"RUNNING", "REFUSED", "ABORTED"},
            "RUNNING": {"COMPLETED", "ABORTED"},
        }
        if state not in allowed.get(self.state, set()):
            raise ValueError(f"Forbidden transition {self.state} -> {state}")
        if state == "RUNNING" and not self._scenario_ids:
            raise ValueError("No scenarios configured")
        if (
            state == "COMPLETED"
            and frozenset(r.scenario_id for r in self.results) != self._scenario_ids
        ):
            raise ValueError("Missing results")
        self._state = state
        if state in ("COMPLETED", "ABORTED", "REFUSED"):
            self.finished_at = finished_at or self.clock().isoformat()

    def record(self, result: ScenarioResult) -> None:
        if (
            self.state != "RUNNING"
            or result.scenario_id not in self._scenario_ids
            or any(r.scenario_id == result.scenario_id for r in self.results)
        ):
            raise ValueError("Cannot record result")
        result.as_dict()
        self._results.append(result)

    def as_dict(self) -> dict[str, Any]:
        return validate(
            "run",
            {
                "apiVersion": "ai-qa/v1",
                "id": self.id,
                "environment": self.environment,
                "commits": dict(self.commits),
                "state": self.state,
                "refusal_reason": self.refusal_reason,
                "abort_reason": self.abort_reason,
                "agent": {"kind": self.agent_kind, "model": self.agent_model},
                "budget": asdict(self.budget),
                "pid": self.pid,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "results": [r.as_dict() for r in self.results],
            },
        )
