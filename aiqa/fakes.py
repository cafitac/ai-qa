from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from .contracts import (
    EnvironmentDescriptor,
    InvalidInput,
    Scenario,
    load_yaml,
    parse_scenarios,
)
from .ports import AgentContext, AgentOutput
from .storage import atomic_write


class FileDescriptorSource:
    def __init__(self, path: Path):
        self.path = path

    def get(self, environment: str) -> EnvironmentDescriptor | None:
        if self.path.suffix.lower() == ".json":
            try:
                value = json.loads(self.path.read_text(encoding="utf-8"))
            except (
                OSError,
                UnicodeDecodeError,
                ValueError,
                RecursionError,
            ) as exc:
                raise InvalidInput(f"Cannot read input: {self.path}") from exc
        elif self.path.suffix.lower() in (".yaml", ".yml"):
            value = load_yaml(self.path)
        else:
            raise InvalidInput("Descriptor must be JSON or YAML")
        descriptor = EnvironmentDescriptor.parse(value)
        return descriptor if descriptor.data["name"] == environment else None


class FileScenarioSource:
    """A single file for a single-service descriptor, or a directory of service files."""

    def __init__(self, path: Path):
        self.path = path
        self._file_service: str | None = None

    def load(
        self, service: str, repo: str, commit: str, timeout_cap: int
    ) -> list[Scenario]:
        if not self.path.is_dir():
            if self._file_service is not None and self._file_service != service:
                raise InvalidInput(
                    "Multi-service descriptors require a scenario directory"
                )
            self._file_service = service
        path = self.path / f"{service}.yaml" if self.path.is_dir() else self.path
        if self.path.is_dir() and not path.exists():
            return []
        return parse_scenarios(load_yaml(path), service, timeout_cap)


class FakeAgentRunner:
    """Development-only deterministic runner. Never invokes an agent or browser."""

    def __init__(
        self,
        outputs: Sequence[AgentOutput] = (),
        statuses: Mapping[str, str] | None = None,
    ):
        self.outputs = list(outputs)
        self.statuses = statuses or {}
        self.calls: list[tuple[Scenario, AgentContext]] = []

    def run(self, scenario: Scenario, context: AgentContext) -> AgentOutput:
        self.calls.append((scenario, context))
        if self.outputs:
            return self.outputs.pop(0)
        path = context.output_dir / "agent.jsonl"
        atomic_write(path, '{"development_fake": true}\n')
        return AgentOutput(
            json.dumps(
                {
                    "status": self.statuses.get(scenario.qualified_id, "PASSED"),
                    "summary": "Development fake result; no browser checks performed",
                    "checks": [],
                }
            ),
            path,
            1,
            0.01,
        )
