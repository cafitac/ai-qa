"""`aiqa mutant validate` (AQP-1 P13a): a seeded defect counts only when the baseline passes a non-LLM HTTP check,
the mutant answers it, and the check then fails on the mutant. Descriptors of existing environments are input;
this module never creates or deletes an environment."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Generator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from .browser import (
    PlaywrightSession,
    ServiceTokenPreflight,
    playwright_errors,
    playwright_factory,
)
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
from .secrets import RunSecrets

Http = Callable[[str, str, object], tuple[int, object]]
# No answer from the app itself: transport error, Access redirect or denial, gateway, missing route.
NO_ANSWER = {0, 301, 302, 303, 307, 308, 401, 403, 404, 405, 502, 503, 504}
MISSING = object()
MAX_BODY = 1 << 20


@contextmanager
def playwright_http(
    config: Config, origins: set[str], factory: Callable[[], Any] = playwright_factory
) -> Generator[Http]:
    """Requests through the owner's Access session (or service token). Every origin is preflighted first and only then is
    the request runtime started, because a sync Playwright runtime cannot be started inside a running one. Redirects are never followed."""
    kind = (
        ServiceTokenPreflight
        if config.access_mode == "service_token"
        else PlaywrightSession
    )
    with kind(config, factory) as session:
        if isinstance(session, ServiceTokenPreflight):
            session.secrets = RunSecrets.load(config, claude=False)
        states = {o: str(session.preflight(o + "/")) for o in sorted(origins)}
        with factory() as playwright:
            contexts = {
                o: playwright.request.new_context(storage_state=state)
                for o, state in states.items()
            }

            def http(method: str, url: str, body: object) -> tuple[int, object]:
                if (context := contexts.get(url_origin(url))) is None:
                    return 0, None
                try:
                    response = context.fetch(
                        url, method=method, data=body, max_redirects=0, timeout=30_000
                    )
                    raw = response.body()
                except playwright_errors():
                    return 0, None
                if len(raw) > MAX_BODY:  # never judge a truncated body
                    return 0, None
                try:
                    return response.status, parse_json(raw)
                except InvalidInput:
                    return response.status, None

            yield http


def dig(value: object, path: str) -> object:
    for part in path.split("."):
        if isinstance(value, list) and part.isascii() and part.isdigit():
            items = cast(list[object], value)
            value = items[int(part)] if int(part) < len(items) else MISSING
        elif isinstance(value, dict):
            value = cast(dict[str, object], value).get(part, MISSING)
        else:
            return MISSING
    return value


def run_steps(
    base: str, steps: list[dict[str, Any]], http: Http
) -> tuple[bool, str | None]:
    """(answered, failure). The check states the correct behavior, so a failure on the mutant is the live defect."""
    for number, step in enumerate(steps, 1):
        label = f"step {number} {step['method']} {step['path']}"
        status, body = http(step["method"], base + step["path"], step.get("json"))
        if status != step["status"]:
            if status in NO_ANSWER:
                return False, f"{label}: no answer from the app (HTTP {status})"
            return True, f"{label}: HTTP {status}, expected {step['status']}"
        for path, want in step.get("equals", {}).items():
            if (got := dig(body, path)) != want:
                shown = "absent" if got is MISSING else repr(got)[:80]
                return True, f"{label}: {path} is {shown}, expected {want!r}"[:300]
    return True, None


def env_service(
    label: str, desc: EnvironmentDescriptor | None, service: str, ref: str, at: datetime
) -> tuple[dict[str, Any] | None, str | None]:
    if desc is None:
        return None, f"{label}: environment descriptor missing"
    if unready := desc.unready_reasons(at):
        return None, f"{label}: environment not ready: {','.join(unready)}"
    for s in desc.data["services"]:
        if s["name"] == service and s["ref"] == ref and s["publicUrl"]:
            return s, None
    return None, f"{label}: service {service}@{ref} is not in {desc.data['name']}"


def validate_mutant(
    entry: dict[str, Any],
    baseline: EnvironmentDescriptor,
    mutant: EnvironmentDescriptor | None,
    baseline_ref: str,
    http: Http,
    at: datetime,
) -> dict[str, Any]:
    pairs = [
        env_service(label, desc, entry["service"], ref, at)
        for label, desc, ref in (
            ("baseline", baseline, baseline_ref),
            ("mutant", mutant, entry["ref"]),
        )
    ]
    reasons = [reason for _, reason in pairs if reason]
    failure = None
    if not reasons:
        steps = entry["check"]["steps"]
        urls = [url_origin(s["publicUrl"]) for s, _ in pairs if s]
        _, base_failure = run_steps(urls[0], steps, http)
        answered, failure = run_steps(urls[1], steps, http)
        if base_failure:
            reasons.append(f"baseline does not pass the check: {base_failure}")
        if not answered:
            reasons.append(f"mutant is not reachable: {failure}")
        elif failure is None:
            reasons.append("defect is not live: the check passes on the mutant")
    commit = (pairs[1][0] or {}).get("commit", "")[:12]
    return {
        **{k: entry[k] for k in ("id", "ref", "category", "axis", "split")},
        "validated": not reasons,
        "reasons": reasons,
        "check_ref": None if reasons else f"http:{commit}:{failure}",
    }


def add_arguments(commands: Any) -> None:
    sub = commands.add_parser("mutant").add_subparsers(
        dest="mutant_command", required=True
    )
    cmd = sub.add_parser("validate")
    cmd.add_argument("--catalog", type=Path, required=True)
    cmd.add_argument(
        "--baseline",
        type=Path,
        required=True,
        help="descriptor JSON of an existing baseline environment",
    )
    cmd.add_argument(
        "--mutant", action="append", default=[], metavar="ID=DESCRIPTOR.json"
    )
    cmd.add_argument("--config", type=Path)


def run(args: argparse.Namespace, clock: Callable[[], datetime]) -> int:
    catalog = validate("mutant-catalog", load_yaml(args.catalog))
    entries = {m["id"]: m for m in catalog["mutants"]}
    if len(entries) != len(catalog["mutants"]) or len(
        {m["ref"] for m in entries.values()}
    ) != len(entries):
        raise InvalidInput("Duplicate mutant id or ref")
    given: dict[str, EnvironmentDescriptor] = {}
    for item in args.mutant:
        name, _, path = item.partition("=")
        if name not in entries or not path or name in given:
            raise InvalidInput(f"Unknown, repeated or malformed --mutant {name!r}")
        given[name] = EnvironmentDescriptor.parse(load_json(Path(path)))
    baseline = EnvironmentDescriptor.parse(load_json(args.baseline))
    at, ref = clock(), catalog.get("baseline_ref", "main")
    names = {m["service"] for m in entries.values()}
    origins = {
        url_origin(svc["publicUrl"])
        for desc in (baseline, *given.values())
        if desc.is_ready(at)
        for svc in desc.data["services"]
        if svc["name"] in names and svc["publicUrl"]
    }
    with playwright_http(Config.load(args.config), origins) as http:
        results = [
            validate_mutant(entries[n], baseline, given.get(n), ref, http, at)
            for n in (given or entries)
        ]
    print(json.dumps({"project": catalog["project"], "results": results}, indent=2))
    return 0 if all(r["validated"] for r in results) else 1
