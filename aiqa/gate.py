from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from .contracts import InvalidInput, Scenario, url_origin
from .ports import AgentContext, AgentOutput
from .run import ScenarioResult
from .screenshots import is_screenshot
from .storage import below_directory
from .usecases import agent_text


def navigation_urls(value: Any) -> list[str]:
    urls: list[str] = []
    if isinstance(value, dict):
        value = cast(dict[str, Any], value)
        name = value.get("name", value.get("tool", ""))
        if isinstance(name, str) and name.split("__")[-1] == "browser_navigate":
            arguments = value.get("input", value.get("arguments", {}))
            if isinstance(arguments, str):
                arguments = json.loads(arguments)
            if not isinstance(arguments, dict) or not isinstance(
                cast(dict[str, Any], arguments).get("url"), str
            ):
                raise ValueError("Malformed navigation")
            arguments = cast(dict[str, Any], arguments)
            urls.append(arguments["url"])
        for child in value.values():
            urls.extend(navigation_urls(child))
    elif isinstance(value, list):
        for child in cast(list[Any], value):
            urls.extend(navigation_urls(child))
    return urls


class VerdictGate:
    def accept(
        self,
        scenario: Scenario,
        output: AgentOutput,
        transcript: Path | None,
        files: tuple[Path, ...],
        caps: AgentContext,
    ) -> ScenarioResult:
        def fail(reason: str) -> ScenarioResult:
            return ScenarioResult(
                scenario.qualified_id,
                "FAILED",
                reason,
                reason,
                turns=output.turns,
                seconds=output.seconds,
            )

        if output.timed_out:
            return fail("timeout")
        if output.turns > caps.max_turns:
            return fail("turn_cap")
        if output.exit_code:
            return fail("agent_error")
        try:
            if transcript:
                if not below_directory(transcript, caps.output_dir):
                    return fail("agent_protocol")
                for line in transcript.read_text(encoding="utf-8").splitlines():
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    for url in navigation_urls(event):
                        try:
                            origin = url_origin(url)
                        except InvalidInput:
                            return fail("out_of_scope")
                        if origin not in caps.allowed_origins:
                            return fail("out_of_scope")
            value: Any = json.loads(output.result_text, object_pairs_hook=unique_object)
            if not isinstance(value, dict) or set(cast(dict[str, Any], value)) != {
                "status",
                "summary",
                "checks",
            }:
                raise ValueError("Invalid answer")
            value = cast(dict[str, Any], value)
            if value["status"] not in ("PASSED", "FAILED") or not isinstance(
                value["checks"], list
            ):
                raise ValueError("Invalid verdict")
            agent_text(value["summary"])
            for check in value["checks"]:
                if (
                    not isinstance(check, dict)
                    or set(cast(dict[str, Any], check)) != {"index", "ok", "observed"}
                    or type(cast(dict[str, Any], check)["ok"]) is not bool
                ):
                    raise ValueError("Invalid check")
                check = cast(dict[str, Any], check)
                if type(check["index"]) is not int:
                    raise ValueError("Invalid index")
                agent_text(check["observed"])
            if sorted(check["index"] for check in value["checks"]) != list(
                range(len(scenario.expect))
            ):
                raise ValueError("Missing or duplicate expectations")
            if value["status"] == "PASSED":
                if not all(check["ok"] for check in value["checks"]):
                    return fail("assertion")
                screenshots = [
                    p
                    for p in caps.output_dir.rglob("*")
                    if is_screenshot(p) and below_directory(p, caps.output_dir)
                ]
                if not screenshots:
                    return fail("no_evidence")
            return ScenarioResult(
                scenario.qualified_id,
                value["status"],
                value["summary"],
                checks=tuple(
                    {
                        "expect": scenario.expect[c["index"]],
                        "ok": c["ok"],
                        "observed": c["observed"],
                    }
                    for c in value["checks"]
                ),
                turns=output.turns,
                seconds=output.seconds,
            )
        except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
            return fail("agent_protocol")


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result
