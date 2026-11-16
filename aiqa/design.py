from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

from .contracts import (
    InvalidInput,
    ScenarioLinks,
    load_json,
    load_yaml,
    manifest_links,
    scenario_links,
    validate,
)

Doc = dict[str, Any]
COVERING = ("in", "regression")
# An AC that says stored text is kept as submitted: a preservation phrase and a text subject in the same AC, and no
# other negation once the phrases are taken out ("not stored verbatim", "isn't preserved", "저장되지 않는다").
KEPT = re.compile(
    r"\b(unchanged|unmodified|unaltered|verbatim|identical|preserved|no change"
    r"|as (submitted|entered|typed)|exactly (as|the)|not (be )?(changed|modified|altered))\b"
    r"|변경되지 않|변경 없|수정 없|입력한 대로|그대로",
    re.IGNORECASE,
)
SUBJECT = re.compile(
    r"\b(text|content|string|input|memo|note|message|title|body|whitespace|spaces?|newlines?)\b"
    r"|텍스트|내용|문자|입력|메모|공백|줄바꿈",
    re.IGNORECASE,
)
NEGATION = re.compile(r"\b(not|never|no longer)\b|n't|않|못", re.IGNORECASE)


def keeps_text(ac: str) -> bool:
    return bool(
        KEPT.search(ac)
        and SUBJECT.search(ac)
        and not NEGATION.search(KEPT.sub(" ", ac))
    )


@dataclass(frozen=True)
class Gap:
    code: str
    subject: str
    detail: str


def check(spec: Doc, design: Doc) -> list[Gap]:
    """Pure QA-design gate rules (G1, G2, G3, G5, G7) over validated documents."""
    gaps: list[Gap] = []

    def add(code: str, subject: str, detail: str) -> None:
        gaps.append(Gap(code, subject, detail))

    acs = {a["id"]: a for a in spec["acs"]}
    rs: list[Doc] = design["requirements"]
    cells: list[Doc] = design["matrix"]
    waivers: list[Doc] = design.get("waivers", [])
    reqs = {r["id"]: r for r in reversed(rs)}
    cell_ids = {c["id"] for c in cells}
    waived_cells = {w["cell"] for w in waivers if "cell" in w}
    waived_acs = {w["ac"] for w in waivers if "ac" in w}
    for kind, items in (("AC", spec["acs"]), ("requirement", rs), ("cell", cells)):
        for i, n in Counter(x["id"] for x in items).items():
            if n > 1:
                add("G7_DUPLICATE_ID", i, f"{kind} id appears {n} times")
    for c in cells:
        if c["req"] not in reqs:
            add("G7_DANGLING_REF", c["id"], f"unknown requirement {c['req']}")
    for w in waivers:
        if "split" in w:  # checked against the axes in check_splits
            continue
        ref = w.get("cell") or w["ac"]
        if ref not in (cell_ids if "cell" in w else acs):
            add("G7_DANGLING_REF", ref, f"waiver {w['card']} names an unknown id")
    for r in rs:
        for a in r["ac"]:
            if a not in acs:
                add("G1_AC_UNKNOWN", r["id"], f"{a} is absent from spec")
    for ac_id, ac in acs.items():
        scopes = [r["scope"] for r in rs if ac_id in r["ac"]]
        if ac["scope"] != "in":
            continue
        if not scopes:
            add("G1_AC_UNMAPPED", ac_id, "in-scope AC has no requirement")
        elif not set(scopes) & set(COVERING) and ac_id not in waived_acs:
            add("G1_AC_NOT_COVERED", ac_id, "only hold/excluded requirements")
    for r in rs:
        if r["scope"] in COVERING and r["id"] not in {c["req"] for c in cells}:
            add("G2_REQ_NO_CELL", r["id"], f"{r['scope']} requirement has no cell")
    for c in cells:
        r = reqs.get(c["req"], c)  # dangling req is G7; compare nothing
        for field in ("scope", "risk"):
            if c[field] != r[field]:
                code = f"G3_{field.upper()}_MISMATCH"
                add(code, c["id"], f"{c[field]} != {r['id']} {r[field]}")
        if (
            c["source"] == "observed"
            and not c.get("expected", "").strip()
            and c["id"] not in waived_cells
        ):
            add("G5_OBSERVED_NO_EXPECTED", c["id"], "no expected and no waiver")
    return gaps


def load_splits(path: Path) -> dict[str, tuple[str, str]]:
    """`length_split` cell key -> (source file, required input), from `aiqa axes` JSON."""
    raw = load_json(path)
    doc = cast(Doc, raw) if isinstance(raw, dict) else {}
    cells = doc.get("cells")
    if doc.get("apiVersion") != "ai-qa/axes/v1" or not isinstance(cells, list):
        raise InvalidInput("--axes is not `aiqa axes` output")
    if doc.get("axes") != "observed":
        raise InvalidInput("--axes has no observed cells")
    found: dict[str, tuple[str, str]] = {}
    for item in cast(list[Any], cells):
        cell = cast(Doc, item) if isinstance(item, dict) else {}
        detail = cell.get("detail")
        need = cast(Doc, detail).get("input") if isinstance(detail, dict) else None
        ok = isinstance(cell.get("key"), str) and isinstance(cell.get("file"), str)
        if not ok or (cell.get("kind") == "length_split" and not isinstance(need, str)):
            raise InvalidInput("--axes holds a malformed cell")
        if cell.get("kind") == "length_split":
            found[cell["key"]] = (cell["file"], cast(str, need))
    return found


def check_splits(
    spec: Doc,
    design: Doc,
    derived: dict[str, tuple[str, str]],
    scope: tuple[str, ...] = (),
) -> list[Gap]:
    """G8: every derived `length_split` cell under a `scope` path prefix (all, when empty) is covered by an in-scope
    cell or waived. A reference to a split that does not exist is G7, whatever the cell's scope."""
    named = {k for c in design["matrix"] for k in c.get("splits", [])}
    covered = {
        k
        for c in design["matrix"]
        if c["scope"] in COVERING
        for k in c.get("splits", [])
    }
    waived = {w["split"] for w in design.get("waivers", []) if "split" in w}
    unchanged = any(keeps_text(a["text"]) for a in spec["acs"] if a["scope"] == "in")
    gaps = [
        Gap("G7_DANGLING_REF", k, "split names no axes length_split cell")
        for k in sorted((named | waived) - derived.keys())
    ]
    for key, (file, need) in sorted(derived.items()):
        if scope and not file.startswith(scope):
            continue
        if key.endswith("#whitespace_preserved") and not unchanged:
            continue  # only a no-change AC makes it a requirement
        if key not in covered | waived:
            gaps.append(Gap("G8_SPLIT_MISSING", key, need))
    return gaps


def check_linkage(design: Doc, scenarios: list[ScenarioLinks]) -> list[Gap]:
    """Pure scenario-linkage rules: G4 (cell -> scenario or waiver), G6 (budget)."""
    gaps: list[Gap] = []
    waived = {w["cell"] for w in design.get("waivers", []) if "cell" in w}
    live = [c for c in design["matrix"] if c["scope"] in COVERING]
    covered = {c for s in scenarios for c in s.cells}
    for c in live:
        if c["id"] not in covered and c["id"] not in waived:
            gaps.append(Gap("G4_CELL_UNTESTED", c["id"], "no scenario and no waiver"))
    tiers: list[str] = sorted(design["budget"])
    for tier in tiers:
        limits = design["budget"][tier]
        cells = {c["id"] for c in live if c["risk"] == tier} - waived
        if not cells:  # a waiver exempts only its own cell, never the tier
            continue
        mine = [s for s in scenarios if cells & set(s.cells)]
        neg = sum(s.kind == "negative" for s in mine)
        bnd = sum(s.kind == "boundary" for s in mine)
        short = [
            f"{name} {have} < {need}"
            for name, have, need in (
                ("scenarios", len(mine), limits["min"]),
                ("negative", neg, limits["minNegative"]),
                ("boundary", bnd, limits["minBoundary"]),
                ("nonHappy", neg + bnd, limits["nonHappyShare"] * len(mine)),
            )
            if have < need - 1e-9
        ]
        if short:
            gaps.append(Gap("G6_BUDGET_SHORT", tier, ", ".join(short)))
    return gaps


def load_linkage(path: Path) -> list[ScenarioLinks]:
    """A directory of `<service>.yaml` scenario files, or a qa/manifest.json file."""
    if path.is_dir():
        found: list[ScenarioLinks] = []
        for file in sorted(path.glob("*.yaml")):
            found += scenario_links(load_yaml(file), file.stem)
        return found
    return manifest_links(load_json(path))


def run_check(
    spec: Path,
    design: Path,
    scenarios: Path | None,
    fmt: str,
    axes: Path | None = None,
    axes_scope: tuple[str, ...] = (),
) -> int:
    spec_doc = validate("spec", load_json(spec))
    design_doc = validate("qa-design", load_yaml(design))
    if spec_doc["feature"] != design_doc["feature"]:
        raise InvalidInput("Spec and design name different features")
    linked = None if scenarios is None else load_linkage(scenarios)
    gaps = check(spec_doc, design_doc)
    if axes is not None:
        gaps += check_splits(spec_doc, design_doc, load_splits(axes), axes_scope)
    if linked is not None:
        gaps += check_linkage(design_doc, linked)
    if fmt == "json":
        print(json.dumps({"ok": not gaps, "gaps": [asdict(g) for g in gaps]}))
    else:
        print("\n".join(f"{g.code} {g.subject}: {g.detail}" for g in gaps) or "ok")
    return int(bool(gaps))
