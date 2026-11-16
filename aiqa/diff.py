"""Criteria edit rate diagnostic (AQP-1 P12 / design 07, Metric definitions): match ids,
count reference additions, removals and criteria edits over the union, excluding steps-only
edits and bookkeeping. Compare normalized expect sets, sorted ac/cells and kind (happy);
then normalized ordered steps and start (/). Normalize whitespace and case only in text.
Set SHA is sha256 of json.dumps(validated_doc, sort_keys=True, separators=(",", ":"),
ensure_ascii=False).encode("utf-8"), independent of YAML formatting.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from .contracts import InvalidInput, Scenario, ScenarioLinks, load_yaml, validate


def scenario_set_sha(doc: dict[str, Any]) -> str:
    validated_doc = validate("scenario-file", doc)
    return hashlib.sha256(
        json.dumps(
            validated_doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()


def _index(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    items: list[dict[str, Any]] = validate("scenario-file", doc)["scenarios"]
    indexed = {item["id"]: item for item in items}
    if len(indexed) != len(items):
        raise InvalidInput("Duplicate scenario id")
    return indexed


def _normalize(text: str) -> str:
    return " ".join(text.split()).casefold()


def _criteria(item: dict[str, Any]) -> tuple[object, ...]:
    return (
        frozenset(_normalize(text) for text in item["expect"]),
        tuple(sorted(item.get("ac", []))),
        tuple(sorted(item.get("cells", []))),
        item.get("kind", ScenarioLinks.kind),
    )


def _steps(item: dict[str, Any]) -> tuple[object, ...]:
    return tuple(_normalize(text) for text in item["steps"]), item.get(
        "start", Scenario.start
    )


def diff_sets(generated: dict[str, Any], reference: dict[str, Any]) -> dict[str, Any]:
    gen, ref = _index(generated), _index(reference)
    scenarios = {
        "added": sorted(ref.keys() - gen.keys()),
        "removed": sorted(gen.keys() - ref.keys()),
        "criteria_changed": [],
        "steps_only": [],
    }
    unchanged = 0
    for key in sorted(gen.keys() & ref.keys()):
        if _criteria(gen[key]) != _criteria(ref[key]):
            scenarios["criteria_changed"].append(key)
        elif _steps(gen[key]) != _steps(ref[key]):
            scenarios["steps_only"].append(key)
        else:
            unchanged += 1
    counts = {name: len(ids) for name, ids in scenarios.items()}
    counts["unchanged"] = unchanged
    union = sum(counts.values())
    edits = counts["added"] + counts["removed"] + counts["criteria_changed"]
    return {
        "apiVersion": "ai-qa/edit-diff/v1",
        "generated_sha": scenario_set_sha(generated),
        "reference_sha": scenario_set_sha(reference),
        "counts": counts,
        "union": union,
        "edit_rate": edits / union if union else None,
        "scenarios": scenarios,
    }


def add_arguments(commands: Any) -> None:
    cmd = commands.add_parser("diff")
    cmd.add_argument("generated", type=Path)
    cmd.add_argument("reference", type=Path)


def run(args: argparse.Namespace) -> int:
    generated = validate("scenario-file", load_yaml(args.generated))
    reference = validate("scenario-file", load_yaml(args.reference))
    print(json.dumps(diff_sets(generated, reference), indent=2, sort_keys=True))
    return 0
