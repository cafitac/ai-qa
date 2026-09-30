from __future__ import annotations

import json
import math
import os
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import urlsplit

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

from .clock import default_clock


class InvalidInput(ValueError):
    pass


class _Validator(Protocol):
    def iter_errors(self, instance: object) -> Iterator[ValidationError]: ...


def validate(kind: str, value: object) -> dict[str, Any]:
    root = Path(__file__).parent / "schemas"
    if not root.exists():
        root = Path(__file__).parent.parent / "schemas"
    schema = json.loads((root / f"{kind}.schema.json").read_text())
    try:
        # User files may contain escaped lone surrogates, including object keys.
        pending: list[object] = [value]
        seen: set[int] = set()
        while pending:
            item = pending.pop()
            if isinstance(item, float) and not math.isfinite(item):
                raise ValueError("Non-finite number")
            if isinstance(item, str):
                item.encode("utf-8")
            elif isinstance(item, (dict, list)) and id(cast(object, item)) not in seen:
                seen.add(id(cast(object, item)))
                if isinstance(item, dict):
                    mapping = cast(dict[object, object], item)
                    pending.extend(mapping.keys())
                    pending.extend(mapping.values())
                else:
                    pending.extend(cast(list[object], item))
        errors = list(
            cast(
                _Validator, Draft202012Validator(schema, format_checker=FormatChecker())
            ).iter_errors(value)
        )
        if errors:
            raise InvalidInput("Input does not match " + kind + " schema")
    except (ValueError, TypeError, RecursionError, OverflowError) as exc:
        raise InvalidInput("Input does not match " + kind + " schema") from exc
    return cast(dict[str, Any], value)


class _StringTimestampLoader(yaml.SafeLoader):
    """Keep YAML timestamps as contract strings without changing SafeLoader globally."""


_StringTimestampLoader.yaml_implicit_resolvers = {
    key: [entry for entry in entries if entry[0] != "tag:yaml.org,2002:timestamp"]
    for key, entries in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def parse_yaml(content: str | bytes) -> object:
    try:
        text = content.decode("utf-8") if isinstance(content, bytes) else content
        return yaml.load(text, Loader=_StringTimestampLoader)
    except (
        UnicodeError,
        yaml.YAMLError,
        RecursionError,
        ValueError,
        OverflowError,
    ) as exc:
        raise InvalidInput("Invalid YAML input") from exc


def parse_json(content: str | bytes) -> object:
    try:
        text = content.decode("utf-8") if isinstance(content, bytes) else content
        return json.loads(text)
    except (UnicodeError, RecursionError, ValueError, OverflowError) as exc:
        raise InvalidInput("Invalid JSON input") from exc


def load_yaml(path: Path) -> object:
    try:
        return parse_yaml(path.read_bytes())
    except (OSError, InvalidInput) as exc:
        raise InvalidInput(f"Cannot read input: {path}") from exc


def load_json(path: Path) -> object:
    try:
        return parse_json(path.read_bytes())
    except (OSError, InvalidInput) as exc:
        raise InvalidInput(f"Cannot read input: {path}") from exc


def duration(value: str) -> int:
    if not re.fullmatch(r"[1-9][0-9]*[smhd]", value) or len(value) > 10:
        raise InvalidInput("Invalid duration")
    seconds = int(value[:-1]) * {"s": 1, "m": 60, "h": 3600, "d": 86400}[value[-1]]
    if seconds > 3650 * 86400:
        raise InvalidInput("Duration exceeds 3650d")
    return seconds


def env_name(value: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,30}", value):
        raise InvalidInput("Invalid environment name")
    return value


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    service: str
    steps: tuple[str, ...]
    expect: tuple[str, ...]
    start: str = "/"
    tags: tuple[str, ...] = ()
    timeout: str | None = None

    @property
    def qualified_id(self) -> str:
        return f"{self.service}/{self.id}"


def parse_scenarios(
    value: object, service: str, timeout_cap: int = 300
) -> list[Scenario]:
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,20}", service):
        raise InvalidInput("Invalid service name")
    data = validate("scenario-file", value)
    result: list[Scenario] = []
    ids: set[str] = set()
    for item in data["scenarios"]:
        if not re.fullmatch(r"[a-z][a-z0-9-]{1,40}", item["id"]):
            raise InvalidInput("Invalid scenario id")
        if item["id"] in ids:
            raise InvalidInput("Duplicate scenario id")
        ids.add(item["id"])
        if item.get("timeout") and duration(item["timeout"]) > timeout_cap:
            raise InvalidInput("Scenario timeout exceeds run cap")
        result.append(
            Scenario(
                item["id"],
                item["title"],
                service,
                tuple(item["steps"]),
                tuple(item["expect"]),
                item.get("start", "/"),
                tuple(item.get("tags", [])),
                item.get("timeout"),
            )
        )
    return result


def environment_path(env: Mapping[str, str], name: str) -> str | None:
    value = env.get(name)
    return value if value and value.strip() else None


@dataclass(frozen=True)
class Config:
    dashboard_url: str = "https://preview-hub.cafitac.com"
    access_team_domain: str = "cafitac.cloudflareaccess.com"
    agent_kind: str = "claude"
    agent_model: str | None = None
    max_scenarios: int = 20
    max_turns: int = 25
    scenario_timeout: str = "300s"
    protocol_retries: int = 1
    runs_dir: Path = Path("runs")
    state_file: Path = Path("~/.config/aiqa/access-state.json")
    playwright_mcp: str | None = "@playwright/mcp@0.0.83"

    @classmethod
    def parse(cls, value: object, environ: Mapping[str, str] | None = None) -> Config:
        d = validate("config", value)
        env = os.environ if environ is None else environ
        hub, agent, budget = d.get("hub", {}), d.get("agent", {}), d.get("budget", {})
        duration(budget.get("scenario_timeout", "300s"))
        dashboard = hub.get("dashboard_url", cls.dashboard_url)
        if not url_origin(dashboard).startswith("https://"):
            raise InvalidInput("Dashboard URL requires https")
        try:
            runs_path = environment_path(env, "AIQA_RUNS_DIR") or str(
                d.get("runs_dir", "./runs")
            )
            state_path = (
                environment_path(env, "AIQA_STATE_FILE")
                or "~/.config/aiqa/access-state.json"
            )
            if "\x00" in runs_path or "\x00" in state_path:
                raise ValueError("Invalid path")
            return cls(
                **hub,
                agent_kind=agent.get("kind", "claude"),
                agent_model=agent.get("model"),
                **budget,
                runs_dir=Path(runs_path).expanduser(),
                state_file=Path(state_path).expanduser(),
                playwright_mcp=d.get("playwright_mcp", cls.playwright_mcp),
            )
        except (ValueError, RuntimeError) as exc:
            raise InvalidInput("Invalid configured path") from exc

    @classmethod
    def load(
        cls, path: Path | None = None, environ: Mapping[str, str] | None = None
    ) -> Config:
        env = os.environ if environ is None else environ
        config_path = environment_path(env, "AIQA_CONFIG")
        selected = path or (Path(config_path) if config_path else None)
        if selected is None and Path("aiqa.yaml").exists():
            selected = Path("aiqa.yaml")
        return cls.parse(
            load_yaml(selected) if selected else {"apiVersion": "ai-qa/v1"}, env
        )


@dataclass(frozen=True)
class EnvironmentDescriptor:
    data: dict[str, Any]

    @classmethod
    def parse(cls, value: object) -> EnvironmentDescriptor:
        d = validate("environment-descriptor", value)
        for timestamp in (d["createdAt"], d["expiresAt"], d["readiness"]["checkedAt"]):
            try:
                if timestamp != timestamp.strip():
                    raise ValueError("Surrounding whitespace")
                parsed = datetime.fromisoformat(timestamp)
                if parsed.utcoffset() is None:
                    raise ValueError("Timezone required")
            except ValueError as exc:
                raise InvalidInput("Invalid descriptor timestamp") from exc
        names = [s["name"] for s in d["services"]]
        if len(names) != len(set(names)):
            raise InvalidInput("Duplicate descriptor service")
        return cls(d)

    def is_ready(self, at: datetime | None = None) -> bool:
        return (
            datetime.fromisoformat(self.data["expiresAt"]) > (at or default_clock())
            and self.data["state"] == "READY"
            and self.data["readiness"]["allHealthy"] is True
            and bool(self.data["services"])
            and all(s["health"] == "HEALTHY" for s in self.data["services"])
        )

    def commits(self) -> dict[str, str]:
        return {s["name"]: s["commit"] for s in self.data["services"]}

    def origins(self) -> tuple[str, ...]:
        urls = [self.data["entryUrl"], *(s["publicUrl"] for s in self.data["services"])]
        result: set[str] = set()
        for url in urls:
            if url:
                result.add(url_origin(str(url)))
        return tuple(sorted(result))


def url_origin(url: str) -> str:
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url)
            or "\\" in url
        ):
            raise InvalidInput("Invalid descriptor URL")
        host = parsed.hostname
        if ":" in host:
            host = f"[{host}]"
        port = parsed.port
        if port == {"http": 80, "https": 443}[parsed.scheme]:
            port = None
        return f"{parsed.scheme}://{host}" + (f":{port}" if port is not None else "")
    except ValueError as exc:
        raise InvalidInput("Invalid descriptor URL") from exc


PLAYWRIGHT_MCP_PATTERN = re.compile(r"@playwright/mcp@[0-9]+\.[0-9]+\.[0-9]+")
