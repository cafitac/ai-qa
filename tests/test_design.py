import copy
import json

import pytest

from aiqa.cli import main as cli_main
from aiqa.contracts import (
    InvalidInput,
    ScenarioLinks,
    manifest_links,
    parse_scenarios,
    scenario_links,
    validate,
)
from aiqa.design import check, check_linkage

SPEC = {
    "apiVersion": "ai-qa/spec/v1",
    "feature": "20261114-example",
    "acs": [
        {"id": "AC1", "scope": "in", "text": "Title is required"},
        {"id": "AC2", "scope": "in", "text": "Saved note is listed"},
        {"id": "AC3", "scope": "excluded", "text": "Legacy export"},
    ],
}
BUDGET = {"min": 1, "minNegative": 0, "minBoundary": 0, "nonHappyShare": 0}


def cell(i, req, source, scope, risk, expected):
    return {
        "id": f"C-{i}",
        "req": req,
        "axis": "display",
        "platform": "web",
        "source": source,
        "expected": expected,
        "scope": scope,
        "risk": risk,
    }


DESIGN = {
    "apiVersion": "ai-qa/qa-design/v1",
    "feature": "20261114-example",
    "requirements": [
        {"id": "REQ-1", "ac": ["AC1"], "scope": "in", "risk": "R1"},
        {"id": "REQ-2", "ac": ["AC2"], "scope": "regression", "risk": "R3"},
        {"id": "REQ-3", "ac": ["AC3"], "scope": "excluded", "risk": "R4"},
    ],
    "matrix": [
        cell(1, "REQ-1", "normative", "in", "R1", "Empty title is rejected"),
        cell(2, "REQ-2", "observed", "regression", "R3", "Note appears first"),
    ],
    "budget": {r: BUDGET for r in ("R1", "R2", "R3", "R4")},
    "waivers": [],
}
W2 = {"cell": "C-2", "card": "CARD-2", "reason": "r"}


def variant(mutate):
    spec, design = copy.deepcopy(SPEC), copy.deepcopy(DESIGN)
    mutate(spec, design)
    return spec, design


def excluded_ac2(s, d):
    d["requirements"][1]["scope"] = "excluded"
    d["matrix"].pop()


# Each row: mutation of (spec, design) -> exact set of (code, subject) gaps.
CASES = {
    "valid": (lambda s, d: None, set()),
    "unmapped": (
        lambda s, d: d["requirements"][1].update(ac=["AC1"]),
        {("G1_AC_UNMAPPED", "AC2")},
    ),
    "not_covered": (excluded_ac2, {("G1_AC_NOT_COVERED", "AC2")}),
    "ac_waiver": (
        lambda s, d: (
            excluded_ac2(s, d),
            d["waivers"].append({"ac": "AC2", "card": "CARD-1", "reason": "r"}),
        ),
        set(),
    ),
    "unknown_ac": (
        lambda s, d: d["requirements"][0]["ac"].append("AC9"),
        {("G1_AC_UNKNOWN", "REQ-1")},
    ),
    "no_cell": (lambda s, d: d["matrix"].pop(0), {("G2_REQ_NO_CELL", "REQ-1")}),
    "scope": (
        lambda s, d: d["matrix"][0].update(scope="regression"),
        {("G3_SCOPE_MISMATCH", "C-1")},
    ),
    "risk": (
        lambda s, d: d["matrix"][1].update(risk="R1"),
        {("G3_RISK_MISMATCH", "C-2")},
    ),
    "observed_blank": (
        lambda s, d: d["matrix"][1].update(expected="  "),
        {("G5_OBSERVED_NO_EXPECTED", "C-2")},
    ),
    "observed_absent": (
        lambda s, d: d["matrix"][1].pop("expected"),
        {("G5_OBSERVED_NO_EXPECTED", "C-2")},
    ),
    "observed_waived": (
        lambda s, d: (d["matrix"][1].update(expected=""), d["waivers"].append(W2)),
        set(),
    ),
    "dup_req": (
        lambda s, d: d["requirements"].append(d["requirements"][0]),
        {("G7_DUPLICATE_ID", "REQ-1")},
    ),
    "dup_cell": (
        lambda s, d: d["matrix"].append(d["matrix"][0]),
        {("G7_DUPLICATE_ID", "C-1")},
    ),
    "dup_ac": (lambda s, d: s["acs"].append(s["acs"][0]), {("G7_DUPLICATE_ID", "AC1")}),
    "dangling_cell_req": (
        lambda s, d: d["matrix"][0].update(req="REQ-9"),
        {("G7_DANGLING_REF", "C-1"), ("G2_REQ_NO_CELL", "REQ-1")},
    ),
    "dangling_waiver_cell": (
        lambda s, d: d["waivers"].append({**W2, "cell": "C-9"}),
        {("G7_DANGLING_REF", "C-9")},
    ),
    "dangling_waiver_ac": (
        lambda s, d: d["waivers"].append(
            {"ac": "AC9", "card": "CARD-3", "reason": "r"}
        ),
        {("G7_DANGLING_REF", "AC9")},
    ),
}


@pytest.mark.parametrize("name", CASES)
def test_gap_table(name):
    mutate, expected = CASES[name]
    spec, design = variant(mutate)
    validate("spec", spec)
    validate("qa-design", design)
    assert {(g.code, g.subject) for g in check(spec, design)} == expected


def run(tmp_path, spec, design, *extra, raw=None):
    (tmp_path / "spec.json").write_text(json.dumps(spec))
    (tmp_path / "design.yaml").write_text(json.dumps(design) if raw is None else raw)
    argv = ["design", "check", "--spec", str(tmp_path / "spec.json")]
    return cli_main([*argv, "--design", str(tmp_path / "design.yaml"), *extra])


def test_cli_pass_and_gaps(tmp_path, capsys):
    assert run(tmp_path, SPEC, DESIGN) == 0
    assert json.loads(capsys.readouterr().out) == {"ok": True, "gaps": []}
    assert run(tmp_path, SPEC, DESIGN, "--format", "text") == 0
    assert capsys.readouterr().out == "ok\n"
    spec, design = variant(excluded_ac2)
    assert run(tmp_path, spec, design) == 1
    gap = json.loads(capsys.readouterr().out)["gaps"][0]
    assert (gap["code"], gap["subject"]) == ("G1_AC_NOT_COVERED", "AC2")
    assert run(tmp_path, spec, design, "--format", "text") == 1
    assert capsys.readouterr().out.startswith("G1_AC_NOT_COVERED AC2:")


def link(key, cells, kind="happy"):
    return ScenarioLinks(key, tuple(cells), kind)


BOTH = [link("web/a", ["C-1"]), link("web/b", ["C-2"])]


def budget(tier, **limits):
    return lambda d: d["budget"][tier].update(limits)


def waive_c2(d):
    d["waivers"].append(W2)


def waive_c1(d):
    d["waivers"].append({**W2, "cell": "C-1"})


# Each row: (design mutation, scenarios) -> exact set of (code, subject) gaps.
LINKAGE = {
    "valid": (lambda d: None, BOTH, set()),
    "g4_untested": (
        lambda d: None,
        BOTH[:1],
        {("G4_CELL_UNTESTED", "C-2"), ("G6_BUDGET_SHORT", "R3")},
    ),
    "g4_waived": (waive_c2, BOTH[:1], set()),
    "g4_hold_cell_exempt": (
        lambda d: d["matrix"][1].update(scope="hold"),
        BOTH[:1],
        set(),
    ),
    "g4_dangling_scenario_cell": (
        lambda d: None,
        [link("web/a", ["C-1", "C-9"]), link("web/b", ["C-2"])],
        set(),
    ),
    "g6_min": (budget("R1", min=2), BOTH, {("G6_BUDGET_SHORT", "R1")}),
    "g6_min_waived": (
        lambda d: (budget("R1", min=2)(d), waive_c1(d)),
        BOTH,
        set(),
    ),
    "g6_negative": (budget("R1", minNegative=1), BOTH, {("G6_BUDGET_SHORT", "R1")}),
    "g6_negative_met": (
        budget("R1", minNegative=1),
        [link("web/a", ["C-1"], "negative"), BOTH[1]],
        set(),
    ),
    "g6_boundary": (budget("R3", minBoundary=1), BOTH, {("G6_BUDGET_SHORT", "R3")}),
    "g6_share": (
        budget("R1", nonHappyShare=0.5),
        [*BOTH, link("web/c", ["C-1"], "negative"), link("web/d", ["C-1"])],
        {("G6_BUDGET_SHORT", "R1")},
    ),
    "g6_share_met": (
        budget("R1", nonHappyShare=0.5),
        [BOTH[0], link("web/c", ["C-1"], "boundary"), BOTH[1]],
        set(),
    ),
    "g6_tier_without_cells": (budget("R2", min=9), BOTH, set()),
}


@pytest.mark.parametrize("name", LINKAGE)
def test_linkage_table(name):
    mutate, scenarios, expected = LINKAGE[name]
    design = copy.deepcopy(DESIGN)
    design["budget"] = {r: dict(b) for r, b in design["budget"].items()}
    mutate(design)
    validate("qa-design", design)
    got = check_linkage(design, scenarios)
    assert {(g.code, g.subject) for g in got} == expected


def v2(**item):
    return {
        "apiVersion": "ai-qa/v2",
        "scenarios": [
            {"id": "one-a", "title": "T", "steps": ["s"], "expect": ["e"], **item}
        ],
    }


FULL_V2 = {
    "ac": ["AC1"],
    "cells": ["C-1"],
    "kind": "negative",
    "origin": "golden",
    "data": "shard-a",
}


def test_v1_and_v2_load():
    v1 = {**v2(), "apiVersion": "ai-qa/v1"}
    assert [s.id for s in parse_scenarios(v1, "web")] == ["one-a"]
    assert [s.id for s in parse_scenarios(v2(**FULL_V2), "web")] == ["one-a"]
    assert scenario_links(v2(**FULL_V2), "web") == [
        ScenarioLinks("web/one-a", ("C-1",), "negative", ("AC1",), "golden", "shard-a")
    ]
    assert scenario_links(v1, "web") == [ScenarioLinks("web/one-a")]


@pytest.mark.parametrize(
    "doc",
    [
        v2(owner="x"),
        v2(kind="sad"),
        v2(cells=["C-1\n"]),
        v2(cells=[]),
        v2(ac=["AC1", "AC1"]),
        v2(data="Bad Name"),
        {**v2(ac=["AC1"]), "apiVersion": "ai-qa/v1"},
        {**v2(), "apiVersion": "ai-qa/v3"},
    ],
)
def test_v2_unknown_or_misplaced_fields_refused(doc):
    with pytest.raises(InvalidInput):
        parse_scenarios(doc, "web")


MANIFEST = {
    "apiVersion": "ai-qa/manifest/v1",
    "generationId": 1,
    "generatorVersion": 2,
    "rulesetVersion": 3,
    "model": "m",
    "scenarios": [
        {
            "id": "web/one-a",
            "ac": ["AC1"],
            "cells": ["C-1"],
            "kind": "happy",
            "origin": "skeleton",
        },
        {
            "id": "web/one-b",
            "ac": ["AC2"],
            "cells": ["C-2"],
            "kind": "negative",
            "origin": "generated",
        },
    ],
}


def test_manifest_loads_and_refuses_unknown():
    assert [s.key for s in manifest_links(MANIFEST)] == ["web/one-a", "web/one-b"]
    for bad in (
        {**MANIFEST, "extra": 1},
        {**MANIFEST, "scenarios": [{**MANIFEST["scenarios"][0], "x": 1}]},
        {**MANIFEST, "scenarios": [MANIFEST["scenarios"][0]] * 2},
    ):
        with pytest.raises(InvalidInput):
            manifest_links(bad)


def scenario_dir(tmp_path, *docs):
    d = tmp_path / "scenarios"
    d.mkdir()
    for name, doc in docs:
        (d / f"{name}.yaml").write_text(json.dumps(doc))
    return d


def two_cell_files(tmp_path):
    a = {**v2(cells=["C-1"]), "scenarios": [{**v2(cells=["C-1"])["scenarios"][0]}]}
    b = v2(cells=["C-2"])
    return scenario_dir(tmp_path, ("web", a), ("api", b))


def test_cli_scenarios_dir_and_manifest(tmp_path, capsys):
    assert (
        run(tmp_path, SPEC, DESIGN, "--scenarios", str(two_cell_files(tmp_path))) == 0
    )
    assert json.loads(capsys.readouterr().out) == {"ok": True, "gaps": []}
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(MANIFEST))
    assert run(tmp_path, SPEC, DESIGN, "--scenarios", str(manifest)) == 0
    capsys.readouterr()
    partial = {**MANIFEST, "scenarios": MANIFEST["scenarios"][:1]}
    manifest.write_text(json.dumps(partial))
    assert run(tmp_path, SPEC, DESIGN, "--scenarios", str(manifest)) == 1
    codes = {g["code"] for g in json.loads(capsys.readouterr().out)["gaps"]}
    assert codes == {"G4_CELL_UNTESTED", "G6_BUDGET_SHORT"}


def test_cli_scenarios_invalid_exits_2(tmp_path, capsys):
    broken = scenario_dir(tmp_path, ("web", v2(owner="x")))
    assert run(tmp_path, SPEC, DESIGN, "--scenarios", str(broken)) == 2
    assert "schema" in capsys.readouterr().out
    missing = str(tmp_path / "nope.json")
    assert run(tmp_path, SPEC, DESIGN, "--scenarios", missing) == 2
    (tmp_path / "bad.json").write_text("{not json")
    assert run(tmp_path, SPEC, DESIGN, "--scenarios", str(tmp_path / "bad.json")) == 2


INVALID = {
    "waiver_cell_and_ac": lambda s, d: d["waivers"].append({**W2, "ac": "AC1"}),
    "normative_empty": lambda s, d: d["matrix"][0].update(expected=""),
    "bad_id": lambda s, d: d["requirements"][0].update(id="REQ-1\n"),
    "extra_field": lambda s, d: d["matrix"][0].update(owner="x"),
    "spec_scope": lambda s, d: s["acs"][0].update(scope="hold"),
    "no_budget": lambda s, d: d.pop("budget"),
}


@pytest.mark.parametrize("name", INVALID)
def test_cli_schema_invalid_exits_2(tmp_path, capsys, name):
    assert run(tmp_path, *variant(INVALID[name])) == 2
    assert "schema" in capsys.readouterr().out


@pytest.mark.parametrize("raw", ["requirements: [unclosed", "- a\n- b\n", ""])
def test_cli_malformed_design_exits_2(tmp_path, raw):
    assert run(tmp_path, SPEC, DESIGN, raw=raw) == 2


def test_cli_feature_mismatch_exits_2(tmp_path, capsys):
    design = {**DESIGN, "feature": "other-feature"}
    assert run(tmp_path, SPEC, design) == 2
    assert "different features" in capsys.readouterr().out


def test_cli_bad_spec_exits_2(tmp_path):
    assert run(tmp_path, SPEC, DESIGN) == 0
    (tmp_path / "spec.json").write_text("{not json")
    argv = ["design", "check", "--spec", str(tmp_path / "spec.json")]
    assert cli_main([*argv, "--design", str(tmp_path / "design.yaml")]) == 2


def test_cli_missing_design_exits_2(tmp_path):
    assert run(tmp_path, SPEC, DESIGN) == 0
    argv = ["design", "check", "--spec", str(tmp_path / "spec.json")]
    assert cli_main([*argv, "--design", str(tmp_path / "missing.yaml")]) == 2
