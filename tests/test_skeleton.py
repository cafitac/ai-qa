from __future__ import annotations

# This unit never reads the clock, so no frozen clock is needed.
import copy
import json
import re

import pytest
import yaml

from aiqa.cli import main as cli_main
from aiqa.contracts import (
    InvalidInput,
    load_yaml,
    parse_yaml,
    scenario_links,
    validate,
)
from aiqa.design import check_linkage
from aiqa.skeleton import expand, run_skeleton, skeleton_file


def design(axes=("display", "flow", "validation", "boundary"), risk="R1"):
    return validate(
        "qa-design",
        {
            "apiVersion": "ai-qa/qa-design/v1",
            "feature": "skeleton-example",
            "requirements": [
                {"id": f"REQ-{i}", "ac": [f"AC{i}"], "scope": "in", "risk": risk}
                for i in range(1, 4)
            ],
            "matrix": [
                {
                    "id": f"C-{i}",
                    "req": f"REQ-{min(i, 3)}",
                    "axis": axis,
                    "platform": "web",
                    "source": "normative",
                    "expected": "Expected " * 100,
                    "scope": "in",
                    "risk": risk,
                }
                for i, axis in enumerate(axes, 1)
            ],
            "budget": {
                r: {"min": 1, "minNegative": 0, "minBoundary": 0, "nonHappyShare": 0}
                for r in ("R1", "R2", "R3", "R4")
            },
        },
    )


def test_ac3_and_determinism():
    d = design()
    original = copy.deepcopy(d)
    doc = validate("scenario-file", skeleton_file(d))
    assert not check_linkage(d, scenario_links(doc, "web"))
    scenarios = doc["scenarios"]
    for req in d["requirements"]:
        kinds = {s["kind"] for s in scenarios if req["id"] in s["tags"]}
        assert {"negative", "boundary"} <= kinds
    assert sum(s["kind"] != "happy" for s in scenarios) >= len(scenarios) / 2
    assert all(s["origin"] == "skeleton" for s in scenarios)
    assert (
        "".join(scenarios[0]["expect"]) == ("Expected " * 100).strip()
    )  # 899 chars, 2 items
    ids = [s["id"] for s in scenarios]
    assert len(ids) == len(set(ids))
    assert "sk-c-4-bnd" in ids
    assert all(re.fullmatch(r"[a-z][a-z0-9-]{1,40}", id) for id in ids)
    assert d == original
    d["matrix"].reverse()
    d["requirements"].reverse()
    assert skeleton_file(d) == doc


def test_exemptions_and_strict_budget():
    d = design(risk="R3")
    d["matrix"][1]["scope"] = "hold"
    d["matrix"][2]["scope"] = "excluded"
    d["waivers"] = [{"cell": "C-4", "card": "CARD-1", "reason": "Deferred"}]
    d["budget"]["R3"].update(min=10, minNegative=3, minBoundary=2, nonHappyShare=0.8)
    doc = skeleton_file(validate("qa-design", d))
    assert all(s["cells"] == ["C-1"] for s in doc["scenarios"])
    assert not check_linkage(d, scenario_links(doc, "web"))
    negatives = [s for s in doc["scenarios"] if s["kind"] == "negative"]
    assert [s["id"] for s in negatives[:3]] == [
        "sk-c-1-neg",
        "sk-c-1-neg2",
        "sk-c-1-neg3",
    ]
    assert "missing input" in negatives[0]["title"]
    assert "invalid value" in negatives[1]["steps"][0]
    d["budget"]["R3"]["nonHappyShare"] = 1
    with pytest.raises(InvalidInput, match="Unsatisfiable"):
        expand(d)
    d = design()
    d["matrix"] = [{**d["matrix"][0], "id": f"C-{i}"} for i in range(1, 52)]
    with pytest.raises(InvalidInput, match="50-scenario"):
        expand(d)
    d = design()
    d["budget"]["R1"]["min"] = 51
    with pytest.raises(InvalidInput, match="50-scenario"):
        skeleton_file(d)


def test_rejects_unsound_references(tmp_path):
    d = design()
    d["matrix"].append({**d["matrix"][0], "id": "C-01"})
    ids = [s["id"] for s in expand(d)]
    assert {"sk-c-1", "sk-c-01"} <= set(ids) and len(ids) == len(set(ids))
    for mutate, match in (
        (lambda d: d["matrix"].append(dict(d["matrix"][0])), "Duplicate cell"),
        (lambda d: d["matrix"][0].update(req="REQ-9"), "unknown requirement"),
        (
            lambda d: d["requirements"][0].update(ac=[f"AC{i}" for i in range(21)]),
            "ACs",
        ),
    ):
        bad = design()
        mutate(bad)
        with pytest.raises(InvalidInput, match=match):
            expand(bad)
    path = tmp_path / "bad.json"
    bad = design()
    bad["matrix"][0]["req"] = "REQ-9"
    path.write_text(json.dumps(bad))
    assert cli_main(["design", "skeleton", "--design", str(path)]) == 2
    path.write_text(json.dumps(design()))
    missing = tmp_path / "absent" / "web.yaml"
    assert (
        cli_main(["design", "skeleton", "--design", str(path), "--out", str(missing)])
        == 2
    )


def test_cli_round_trip(tmp_path, capsys):
    d = design()
    d["matrix"][0]["expected"] = "Shows \U0001f600 한글 \x7f \x85 \u2028 end"
    path = tmp_path / "design.json"
    path.write_text(yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")
    spec = tmp_path / "spec.json"
    acs = [{"id": f"AC{i}", "scope": "in", "text": "Works"} for i in range(1, 4)]
    spec_doc = {"apiVersion": "ai-qa/spec/v1", "feature": d["feature"], "acs": acs}
    spec.write_text(json.dumps(spec_doc))
    out = tmp_path / "scenarios"
    out.mkdir()
    target = out / "web.yaml"
    args = ["design", "skeleton", "--design", str(path), "--out", str(target)]
    assert cli_main(args) == 0
    assert target.read_text().endswith("\n")
    args = ["design", "check", "--spec", str(spec), "--design", str(path)]
    assert cli_main([*args, "--scenarios", str(out)]) == 0
    assert json.loads(capsys.readouterr().out)["ok"]
    assert run_skeleton(path, None) == 0
    assert parse_yaml(capsys.readouterr().out) == skeleton_file(d)
    assert load_yaml(target) == skeleton_file(d)
