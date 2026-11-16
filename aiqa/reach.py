"""`aiqa mutant reach` (AQP-1 F3): a MISSED mutant's no-agent diagnosis. The text the baseline run typed into the page is
replayed over HTTP against the baseline and the mutant environments. A pair that answers differently means a scenario
input reaches the defect (REACHED, so a PASSED verdict is an oracle or agent question); identical answers everywhere
mean none does (UNREACHED, so a coverage gap). It makes no agent call, writes no ledger row and changes no verdict rule.
It does write: each replayed input is sent to both environments, as `mutant validate` sends its check steps."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from . import mutants
from .contracts import (
    Config,
    EnvironmentDescriptor,
    InvalidInput,
    load_json,
    load_yaml,
    parse_json,
    url_origin,
    validate,
)
from .mutants import NO_ANSWER, Http, dig, same

PLACEHOLDER = "{input}"
UNANSWERED = NO_ANSWER | {429}  # a rate limit says nothing about the defect


def tool_calls(log: Path) -> Iterator[tuple[str, dict[str, Any]]]:
    """`(tool name, input)` of every tool_use in a stream-json `agent.jsonl`; unreadable lines are skipped."""
    for line in log.read_text(encoding="utf-8", errors="replace").split("\n"):
        try:
            event = parse_json(line)
        except InvalidInput:
            continue
        message = (
            cast(dict[str, Any], event).get("message")
            if isinstance(event, dict)
            else None
        )
        content = (
            cast(dict[str, Any], message).get("content")
            if isinstance(message, dict)
            else None
        )
        for block in cast(list[object], content) if isinstance(content, list) else []:
            if isinstance(block, dict):
                use = cast(dict[str, Any], block)
                args = use.get("input")
                if use.get("type") == "tool_use" and isinstance(use.get("name"), str):
                    yield (
                        use["name"],
                        cast(dict[str, Any], args) if isinstance(args, dict) else {},
                    )


def typed_inputs(log: Path) -> list[str]:
    """Texts typed into the page and then submitted: `browser_type` with `submit`, or a click or Enter before the next
    type or navigation."""
    pending: str | None = None
    found: list[str] = []
    for name, args in tool_calls(log):
        tool, text = name.split("__")[-1], args.get("text")
        if tool == "browser_type" and isinstance(text, str):
            if args.get("submit") is True:
                found.append(text)
            pending = None if args.get("submit") is True else text
        elif pending is not None and (
            tool == "browser_click"
            or (tool == "browser_press_key" and args.get("key") == "Enter")
        ):
            found.append(pending)
            pending = None
        elif tool in ("browser_navigate", "browser_navigate_back"):
            pending = None
    return found


def substitute(value: object, text: str) -> tuple[object, int]:
    """`value` with every `{input}` replaced by `text`, and how many were replaced."""
    if isinstance(value, str):
        return value.replace(PLACEHOLDER, text), value.count(PLACEHOLDER)
    if isinstance(value, list):
        pairs = [substitute(v, text) for v in cast(list[object], value)]
        return [v for v, _ in pairs], sum(n for _, n in pairs)
    if isinstance(value, dict):
        items = {
            k: substitute(v, text) for k, v in cast(dict[str, object], value).items()
        }
        return {k: v for k, (v, _) in items.items()}, sum(n for _, n in items.values())
    return value, 0


def observe(
    http: Http, base: str, spec: dict[str, Any], sent: str
) -> tuple[int, list[object]]:
    """The app's answer to one request: status plus the compared response fields (`MISSING` when absent)."""
    request = spec["request"]
    body, _ = substitute(request["json"], sent)
    status, answer = http(request["method"], base + request["path"], body)
    return status, [dig(answer, path) for path in spec["compare"]]


def reach(
    spec: dict[str, Any],
    inputs: list[tuple[str, str]],
    baseline: tuple[Http, str],
    mutant: tuple[Http, str],
) -> dict[str, Any]:
    """`inputs`: (scenario, typed text) pairs; a text typed twice is sent once. Needs `trim` (what the page does before
    sending) and a non-empty `compare` (response fields) in `spec`, and an `{input}` in its request body, or it raises
    InvalidInput, because a replay that cannot differ would read as UNREACHED. REACHED when some input is answered
    differently. UNREACHED only when every input was answered by both sides, identically, and the baseline accepted
    (2xx) at least one: a replay both sides reject proves nothing. Each sent input is written to both environments."""
    if not (isinstance(spec.get("trim"), bool) and spec.get("compare")):
        raise InvalidInput("The replay spec needs trim and a non-empty compare")
    if not substitute(spec["request"]["json"], "")[1]:
        raise InvalidInput(f"request.json must hold {PLACEHOLDER!r}")
    rows: list[dict[str, Any]] = []
    first: dict[str, str] = {}
    for scenario, text in inputs:
        first.setdefault(text, scenario)
    for text, scenario in first.items():
        sent = text.strip() if spec["trim"] else text
        (b_status, b_fields), (m_status, m_fields) = (
            observe(http, base, spec, sent) for http, base in (baseline, mutant)
        )
        answered = UNANSWERED.isdisjoint({b_status, m_status})
        rows.append(
            {
                "scenario": scenario,
                "chars": len(sent),
                "baseline_status": b_status,
                "mutant_status": m_status,
                "answered": answered,
                "reached": answered
                and not (b_status == m_status and same(b_fields, m_fields)),
            }
        )
    if any(r["reached"] for r in rows):
        verdict = "REACHED"
    elif not rows:
        verdict = "NO_INPUT"
    elif all(r["answered"] for r in rows) and any(
        200 <= r["baseline_status"] < 300 for r in rows
    ):
        verdict = "UNREACHED"
    else:
        verdict = "INCONCLUSIVE"
    return {"classification": verdict, "inputs": rows}


def agent_logs(run_dir: Path) -> Iterator[tuple[str, Path]]:
    for log in sorted(run_dir.glob("scenarios/*/attempt-*/agent.jsonl")):
        yield log.parts[-3].replace("__", "/", 1), log


def service_url(desc: EnvironmentDescriptor, service: str, at: datetime) -> str:
    if reasons := desc.unready_reasons(at):
        raise InvalidInput(
            f"{desc.data['name']}: environment not ready: {','.join(reasons)}"
        )
    for s in desc.data["services"]:
        if s["name"] == service and s["publicUrl"]:
            return str(s["publicUrl"]).rstrip("/")
    raise InvalidInput(
        f"{desc.data['name']}: service {service} is not in the environment"
    )


def run(args: argparse.Namespace, clock: Callable[[], datetime]) -> int:
    """Exit 0 for REACHED or UNREACHED, 1 when the diagnosis could not decide, 2 for invalid input."""
    spec = validate("reach-replay", load_yaml(args.replay))
    inputs = [
        (f"{scenario}#{n}", text)
        for run_dir in args.run
        for scenario, log in agent_logs(run_dir)
        for n, text in enumerate(typed_inputs(log), 1)
    ]
    urls = [
        service_url(
            EnvironmentDescriptor.parse(load_json(path)), spec["service"], clock()
        )
        for path in (args.baseline, args.mutant)
    ]
    from .secrets import resolve_access

    config = Config.load(args.config)
    if args.access:
        config = replace(config, access_mode=args.access.replace("-", "_"))
    failures: dict[str, str] = {}
    origins = {url_origin(u) for u in urls}
    with mutants.playwright_http(resolve_access(config), origins, failures) as http:
        report = reach(spec, inputs, (http, urls[0]), (http, urls[1]))
    print(json.dumps({**report, "preflight_failures": failures}, indent=2))
    return 0 if report["classification"] in ("REACHED", "UNREACHED") else 1
