"""MISSED-mutant reach diagnosis core (AQP-1 F3; the `aiqa mutant reach` command is the next PR): a no-agent diagnosis. The text the baseline run typed into the page is
replayed over HTTP against the baseline and the mutant environments. A pair that answers differently means a scenario
input reaches the defect (REACHED, so a PASSED verdict is an oracle or agent question); identical answers everywhere
mean none does (UNREACHED, so a coverage gap). It makes no agent call, writes no ledger row and changes no verdict rule.
It does write: each replayed input is sent to both environments, as `mutant validate` sends its check steps."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

from .contracts import InvalidInput, parse_json
from .mutants import NO_ANSWER, Http, dig, same

SUBMIT = ("browser_click", "browser_press_key")
PLACEHOLDER = "{input}"


def tool_calls(log: Path) -> Iterator[tuple[str, dict[str, Any]]]:
    """`(tool name, input)` of every tool_use in a stream-json `agent.jsonl`; unreadable lines are skipped."""
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
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
    """Texts typed into the page and then submitted (a click or key press before the next type or navigation)."""
    pending: str | None = None
    found: list[str] = []
    for name, args in tool_calls(log):
        if name.endswith("browser_type") and isinstance(args.get("text"), str):
            pending = args["text"]
        elif name.endswith(SUBMIT) and pending is not None:
            found.append(pending)
            pending = None
        elif name.endswith("browser_navigate"):
            pending = None
    return found


def substitute(value: object, text: str) -> object:
    if value == PLACEHOLDER:
        return text
    if isinstance(value, list):
        return [substitute(v, text) for v in cast(list[object], value)]
    if isinstance(value, dict):
        return {
            k: substitute(v, text) for k, v in cast(dict[str, object], value).items()
        }
    return value


def observe(
    http: Http, base: str, spec: dict[str, Any], text: str
) -> tuple[int, list[object]]:
    """The app's answer to one input: status plus the compared response fields (`MISSING` when absent)."""
    sent = text.strip() if spec.get("trim", True) else text
    request = spec["request"]
    status, body = http(
        request["method"], base + request["path"], substitute(request["json"], sent)
    )
    return status, [dig(body, path) for path in spec.get("compare", [])]


def reach(
    spec: dict[str, Any],
    inputs: dict[str, str],
    baseline: tuple[Http, str],
    mutant: tuple[Http, str],
) -> dict[str, Any]:
    """`inputs`: scenario id -> typed text. REACHED when some input is answered differently, and
    UNREACHED only when every input was answered identically by both sides."""
    rows: list[dict[str, Any]] = []
    for scenario, text in inputs.items():
        (b_status, b_fields), (m_status, m_fields) = (
            observe(http, base, spec, text) for http, base in (baseline, mutant)
        )
        answered = NO_ANSWER.isdisjoint({b_status, m_status})
        differs = answered and not (b_status == m_status and same(b_fields, m_fields))
        rows.append(
            {
                "scenario": scenario,
                "chars": len(text.strip() if spec.get("trim", True) else text),
                "baseline_status": b_status,
                "mutant_status": m_status,
                "answered": answered,
                "reached": differs,
            }
        )
    if any(r["reached"] for r in rows):
        verdict = "REACHED"
    elif not rows:
        verdict = "NO_INPUT"
    elif all(r["answered"] for r in rows):
        verdict = "UNREACHED"
    else:
        verdict = "INCONCLUSIVE"
    return {"classification": verdict, "inputs": rows}


def agent_logs(run_dir: Path) -> Iterator[tuple[str, Path]]:
    for log in sorted(run_dir.glob("scenarios/*/attempt-*/agent.jsonl")):
        yield log.parts[-3].replace("__", "/", 1), log
