from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .contracts import EnvironmentDescriptor, Scenario
from .run import ScenarioResult


@dataclass(frozen=True)
class AgentContext:
    output_dir: Path
    start_url: str
    allowed_origins: tuple[str, ...]
    max_turns: int
    timeout_seconds: int
    model: str | None = None
    storage_state: Path | None = None


@dataclass(frozen=True)
class AgentOutput:
    result_text: str
    transcript_path: Path | None = None
    turns: int = 0
    seconds: float = 0
    exit_code: int = 0
    timed_out: bool = False


class DescriptorSource(Protocol):
    def get(self, environment: str) -> EnvironmentDescriptor | None: ...


class ScenarioSource(Protocol):
    def load(
        self, service: str, repo: str, commit: str, timeout_cap: int
    ) -> list[Scenario]: ...


class AgentRunner(Protocol):
    def run(self, scenario: Scenario, context: AgentContext) -> AgentOutput: ...


class BrowserSession(Protocol):
    def preflight(self, url: str) -> Path | None: ...


class VerdictGate(Protocol):
    def accept(
        self,
        scenario: Scenario,
        output: AgentOutput,
        transcript: Path | None,
        files: tuple[Path, ...],
        caps: AgentContext,
    ) -> ScenarioResult: ...
