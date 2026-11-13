from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .contracts import InvalidInput, load_json, load_yaml, validate

Doc = dict[str, Any]
COVERING = ("in", "regression")


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


def run_check(spec: Path, design: Path, scenarios: Path | None, fmt: str) -> int:
    if scenarios is not None:
        raise InvalidInput("--scenarios is not supported until ai-qa/v2")
    gaps = check(
        validate("spec", load_json(spec)), validate("qa-design", load_yaml(design))
    )
    if fmt == "json":
        print(json.dumps({"ok": not gaps, "gaps": [asdict(g) for g in gaps]}))
    else:
        print("\n".join(f"{g.code} {g.subject}: {g.detail}" for g in gaps) or "ok")
    return int(bool(gaps))
