"""`aiqa mutant reach` (AQP-1 F3): no agent call, no ledger row. A baseline run's typed text is replayed to the baseline
and mutant environments; an input answered differently reaches the defect."""

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
from .mutants import MISSING, NO_ANSWER, Http, dig, same

PLACEHOLDER = "{input}"
JS_SPACE = " \t\n\v\f\r\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"  # String.prototype.trim
UNANSWERED = NO_ANSWER | {429}  # a rate limit says nothing about the defect


def _get(value: object, key: str) -> object:
    return cast(dict[str, object], value).get(key) if isinstance(value, dict) else None


def tool_calls(log: Path) -> Iterator[tuple[str, dict[str, Any]]]:
    """`(tool name, input)` of every tool_use in a stream-json `agent.jsonl`; unreadable lines are skipped."""
    for line in log.read_text(encoding="utf-8", errors="replace").split("\n"):
        try:
            event = parse_json(line)
        except InvalidInput:
            continue
        content = _get(_get(event, "message"), "content")
        for block in cast(list[object], content) if isinstance(content, list) else []:
            name, args = _get(block, "name"), _get(block, "input")
            if _get(block, "type") == "tool_use" and isinstance(name, str):
                yield name, cast(dict[str, Any], args) if isinstance(args, dict) else {}


def typed_inputs(log: Path) -> list[str]:
    """Texts typed and then submitted (`submit`, a click or Enter before the next navigation), one per field typed
    since the last submit; a `slowly` type appends to its field."""
    pending: dict[str, str] = {}
    found: list[str] = []
    for name, args in tool_calls(log):
        tool, text = name.split("__")[-1], args.get("text")
        field = str(args.get("target") or args.get("ref") or args.get("element"))
        if tool == "browser_type" and isinstance(text, str):
            kept = pending.get(field, "") if args.get("slowly") is True else ""
            pending[field] = kept + text
            if args.get("submit") is True:
                found += pending.values()
                pending = {}
        elif tool == "browser_click" or (
            tool == "browser_press_key" and args.get("key") == "Enter"
        ):
            found += pending.values()
            pending = {}
        elif tool in ("browser_navigate", "browser_navigate_back"):
            pending = {}
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
    """`inputs` are (scenario, typed text) pairs; a text is sent once. REACHED when some input is answered differently,
    UNREACHED only when every input was answered identically and the baseline accepted (2xx) one with a compared field
    present, otherwise INCONCLUSIVE (no answer, 429, both sides reject, nothing compared) or NO_INPUT. A spec without
    `trim`, a list `compare` and an `{input}` in the body could not differ, so it raises InvalidInput."""
    compare = spec.get("compare")
    plain = isinstance(compare, list) and all(
        isinstance(p, str) for p in cast(list[Any], compare)
    )
    if not (isinstance(spec.get("trim"), bool) and plain and compare):
        raise InvalidInput("The replay spec needs trim and a non-empty list compare")
    if not substitute(spec["request"]["json"], "")[1]:
        raise InvalidInput(f"request.json must hold {PLACEHOLDER!r}")
    rows: list[dict[str, Any]] = []
    first: dict[str, str] = {}
    for scenario, text in inputs:
        sent = text.strip(JS_SPACE) if spec["trim"] else text
        first.setdefault(sent, scenario)
    for sent, scenario in first.items():
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
                "compared": any(f is not MISSING for f in b_fields),
                "reached": answered
                and not (b_status == m_status and same(b_fields, m_fields)),
            }
        )
    if any(r["reached"] for r in rows):
        verdict = "REACHED"
    elif not rows:
        verdict = "NO_INPUT"
    elif all(r["answered"] for r in rows) and any(
        200 <= r["baseline_status"] < 300 and r["compared"] for r in rows
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
