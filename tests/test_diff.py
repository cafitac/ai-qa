import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from aiqa.cli import main
from aiqa.contracts import parse_yaml
from aiqa.diff import diff_sets, scenario_set_sha


def scenario(key: str = "same", **changes: Any) -> dict[str, Any]:
    return {
        "id": key,
        "title": "Title",
        "steps": ["Open", "Click"],
        "expect": ["OK", "Ready"],
    } | changes


def doc(*items: dict[str, Any], version: str = "ai-qa/v2") -> dict[str, Any]:
    return {"apiVersion": version, "scenarios": list(items)}


@pytest.mark.parametrize(
    ("changes", "category"),
    [
        ({"expect": ["Wrong"], "steps": ["Other"]}, "criteria_changed"),
        ({"ac": ["AC1"]}, "criteria_changed"),
        ({"cells": ["C-1"]}, "criteria_changed"),
        ({"kind": "negative"}, "criteria_changed"),
        ({"steps": ["Click", "Open"]}, "steps_only"),
        ({"start": "/other"}, "steps_only"),
        (
            {"expect": [" ready ", "ok", "OK"], "steps": [" OPEN\n", "click"]},
            "unchanged",
        ),
        (
            {
                "title": "New",
                "tags": ["tag"],
                "origin": "critic",
                "timeout": "9s",
                "data": "ns",
            },
            "unchanged",
        ),
        ({"kind": "happy", "start": "/"}, "unchanged"),
    ],
)
def test_classification(changes: dict[str, Any], category: str):
    result = diff_sets(doc(scenario()), doc(scenario(**changes)))
    assert result["counts"][category] == 1
    assert result["union"] == 1
    assert result["edit_rate"] == int(category == "criteria_changed")
    if category != "unchanged":
        assert result["scenarios"][category] == ["same"]


def test_union_direction_sorting_and_rate():
    generated = doc(
        scenario("zz"), scenario("aa"), scenario("edit"), scenario("step"), scenario()
    )
    reference = doc(
        scenario("bb"),
        scenario("ab"),
        scenario("edit", expect=["No"]),
        scenario("step", steps=["Go"]),
        scenario(),
    )
    result = diff_sets(generated, reference)
    assert result["scenarios"] == {
        "added": ["ab", "bb"],
        "removed": ["aa", "zz"],
        "criteria_changed": ["edit"],
        "steps_only": ["step"],
    }
    assert result["counts"] == {
        "added": 2,
        "removed": 2,
        "criteria_changed": 1,
        "steps_only": 1,
        "unchanged": 1,
    }
    assert result["union"] == 7
    assert result["edit_rate"] == 5 / 7
    assert diff_sets(doc(), doc())["edit_rate"] is None
    assert diff_sets(doc(), doc())["union"] == 0
    before = scenario(ac=["AC2", "AC1"], cells=["C-2", "C-1"])
    after = scenario(ac=["AC1", "AC2"], cells=["C-1", "C-2"])
    assert diff_sets(doc(before), doc(after))["counts"]["unchanged"] == 1


def test_digest_is_canonical_and_preserves_content():
    original = doc(scenario(title="한글"), version="ai-qa/v1")
    canonical = json.dumps(
        original, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert scenario_set_sha(original) == expected
    for flow in (True, False):
        loaded = parse_yaml(
            yaml.safe_dump(original, default_flow_style=flow, sort_keys=True)
        )
        assert loaded == original
        assert scenario_set_sha(loaded) == expected
    assert (
        scenario_set_sha(doc(scenario(title="Changed"), version="ai-qa/v1")) != expected
    )


@pytest.mark.parametrize(
    ("generated", "reference", "message"),
    [
        (doc(scenario()), doc(scenario()), None),
        ({}, doc(scenario()), "Input does not match scenario-file schema"),
        (doc(scenario()), doc(scenario(), scenario()), "Duplicate scenario id"),
    ],
    ids=["ok", "schema-invalid-generated", "duplicate-id-reference"],
)
def test_cli(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    generated: dict[str, Any],
    reference: dict[str, Any],
    message: str | None,
):
    paths = [tmp_path / "generated.yaml", tmp_path / "reference.yaml"]
    for path, content in zip(paths, (generated, reference)):
        path.write_text(yaml.safe_dump(content))
    assert main(["diff", *map(str, paths)]) == (2 if message else 0)
    output = capsys.readouterr().out
    if message:
        assert message in output
    else:
        expected = diff_sets(generated, reference)
        assert output == json.dumps(expected, indent=2, sort_keys=True) + "\n"
