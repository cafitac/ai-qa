from __future__ import annotations

from collections import Counter
from pathlib import Path

import yaml

from .contracts import InvalidInput, load_yaml, validate
from .design import COVERING, Doc

MIN_NEGATIVE = MIN_BOUNDARY = 1
NON_HAPPY_SHARE = 0.5
MAX_AC = 20  # scenario-file `ac` maxItems
MAX_SCENARIOS = 50  # scenario-file `scenarios` maxItems
MAX_TEXT = 500  # scenario-file `expect` item length
SUFFIX = {"happy": "", "negative": "-neg", "boundary": "-bnd"}
VARIANTS = {
    "happy": ("nominal values",),
    "negative": ("missing input", "invalid value", "unauthorized actor"),
    "boundary": ("minimum", "maximum", "just beyond limit"),
}
PREFERRED = {
    "negative": ("validation", "empty_error", "permission", "disabled_detail"),
    "boundary": ("boundary", "validation"),
}


def _require_references(design: Doc) -> None:
    """The expander needs unique ids, known requirements and a schema-sized `ac` list."""
    reqs: list[Doc] = design["requirements"]
    for kind, items in (("requirement", reqs), ("cell", design["matrix"])):
        for i, n in Counter(x["id"] for x in items).items():
            if n > 1:
                raise InvalidInput(f"Duplicate {kind} id {i}")
    known = {r["id"] for r in reqs}
    for c in design["matrix"]:
        if c["req"] not in known:
            raise InvalidInput(f"Cell {c['id']} names unknown requirement {c['req']}")
    for r in reqs:
        if len(r["ac"]) > MAX_AC:
            raise InvalidInput(f"{r['id']} links more than {MAX_AC} ACs")


def _order(cell_id: str) -> tuple[int, str]:
    return int(cell_id[2:]), cell_id


def expand(design: Doc) -> list[Doc]:
    """Expand validated design cells into deterministic mechanical scenarios."""
    _require_references(design)
    waived = {w["cell"] for w in design.get("waivers", []) if "cell" in w}
    live = [
        c for c in design["matrix"] if c["scope"] in COVERING and c["id"] not in waived
    ]
    cells = sorted(live, key=lambda c: _order(c["id"]))
    reqs = {r["id"]: r for r in design["requirements"]}
    counts: Counter[tuple[str, str]] = Counter()
    result: list[Doc] = []

    def add(cell: Doc, kind: str) -> None:
        ordinal = counts[cell["id"], kind]
        variant = VARIANTS[kind][ordinal % len(VARIANTS[kind])]
        suffix = SUFFIX[kind]
        suffix += str(ordinal + 1) if ordinal else ""
        expected = (
            cell.get("expected") or ""
        ).strip() or "Verify the expected cell behavior."
        result.append(
            {
                "id": f"sk-{cell['id'].lower()}{suffix}",
                "title": f"{cell['req']} {cell['axis']}: {variant}",
                "steps": [f"Exercise {cell['axis']} for {cell['req']} with {variant}."],
                "expect": [
                    expected[i : i + MAX_TEXT]
                    for i in range(0, len(expected), MAX_TEXT)
                ],
                "tags": [cell["req"], cell["axis"]],
                "ac": sorted(reqs[cell["req"]]["ac"]),
                "cells": [cell["id"]],
                "kind": kind,
                "origin": "skeleton",
            }
        )
        counts[cell["id"], kind] += 1

    def slot(mine: list[Doc], kind: str) -> None:
        preferred = [c for c in mine if c["axis"] in PREFERRED[kind]]
        candidates = preferred or mine[:1]
        add(min(candidates, key=lambda c: counts[c["id"], kind]), kind)

    for c in cells:
        kind = "negative" if c["axis"] in PREFERRED["negative"] else "happy"
        add(c, "boundary" if c["axis"] == "boundary" else kind)
    if len(result) > MAX_SCENARIOS:  # the budget loop below can only add more
        raise InvalidInput(f"Skeleton exceeds the {MAX_SCENARIOS}-scenario file limit")
    grouped = {r: [c for c in cells if c["req"] == r] for r in sorted(reqs)}
    for r, mine in grouped.items():
        if mine and reqs[r]["risk"] in ("R1", "R2"):
            minima = {"negative": MIN_NEGATIVE, "boundary": MIN_BOUNDARY}
            for kind, minimum in minima.items():
                while sum(counts[c["id"], kind] for c in mine) < minimum:
                    slot(mine, kind)
    for tier, limits in sorted(design["budget"].items()):
        mine = [c for c in cells if c["risk"] == tier]
        if not mine:
            continue
        targets = sorted({c["req"] for c in mine})
        floor = NON_HAPPY_SHARE if tier in ("R1", "R2") else 0
        share = max(limits["nonHappyShare"], floor)
        for iteration in range(1001):
            happy, neg, bnd = (sum(counts[c["id"], k] for c in mine) for k in VARIANTS)
            total = happy + neg + bnd
            have = (total, neg, bnd, neg + bnd)
            need = tuple(limits[k] for k in ("min", "minNegative", "minBoundary"))
            need += (share * total,)
            if all(h >= n - 1e-9 for h, n in zip(have, need)):
                break
            if iteration == 1000 or (share == 1 and happy):
                raise InvalidInput(f"Unsatisfiable skeleton budget for {tier}")
            if neg < limits["minNegative"]:
                kind = "negative"
            elif bnd < limits["minBoundary"]:
                kind = "boundary"
            else:
                kind = "negative" if neg <= bnd else "boundary"
            target = targets[iteration % len(targets)]
            slot([c for c in mine if c["req"] == target], kind)
    # Stable sorting preserves insertion ordinals within each cell and kind.
    return sorted(
        result, key=lambda s: (*_order(s["cells"][0]), tuple(VARIANTS).index(s["kind"]))
    )


def skeleton_file(design: Doc) -> Doc:
    scenarios = expand(design)
    if len(scenarios) > MAX_SCENARIOS:
        raise InvalidInput(f"Skeleton exceeds the {MAX_SCENARIOS}-scenario file limit")
    return {"apiVersion": "ai-qa/v2", "scenarios": scenarios}


def run_skeleton(design: Path, out: Path | None) -> int:
    doc = skeleton_file(validate("qa-design", load_yaml(design)))
    validate("scenario-file", doc)
    # YAML keeps every code point readable by load_yaml (JSON escapes of control or
    # non-BMP characters do not survive PyYAML); stdout stays ASCII-only.
    dump = yaml.safe_dump(
        doc, allow_unicode=out is not None, sort_keys=False, width=10**6
    )
    if out is None:
        print(dump, end="")
    else:
        try:
            out.write_text(dump, encoding="utf-8")
        except OSError as error:
            raise InvalidInput(
                f"Cannot write output {out}: {error.strerror}"
            ) from error
    return 0
