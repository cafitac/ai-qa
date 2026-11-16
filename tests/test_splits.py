from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from aiqa.axes import extract_axes
from aiqa.axes.fastapi_extractor import LENGTH_SPLITS
from aiqa.cli import main
from aiqa.contracts import InvalidInput, validate
from aiqa.design import check_splits, load_splits

HEAD = "from fastapi import FastAPI\nfrom pydantic import BaseModel, Field\napp = FastAPI()\n"
APP = HEAD + "class Note(BaseModel):\n    text: str = Field(max_length=500)\n"
OTHER = "class U(BaseModel):\n    n: str = Field(max_length=9)\n"
KEY = "app.py::length_split:Note.text#"
EVERY = tuple(LENGTH_SPLITS)
RISKS = {
    r: dict.fromkeys(("min", "minNegative", "minBoundary", "nonHappyShare"), 0)
    for r in ("R1", "R2", "R3", "R4")
}


def axes_file(tmp_path: Path, source: str = APP) -> Path:
    (tmp_path / "app.py").write_text(source)
    (tmp_path / "axes.json").write_text(json.dumps(extract_axes(tmp_path)))
    return tmp_path / "axes.json"


def design(
    *names: str, waived: tuple[str, ...] = (), scope: str = "in"
) -> dict[str, Any]:
    return {
        "matrix": [{"id": "C-1", "scope": scope, "splits": [KEY + s for s in names]}],
        "waivers": [
            {"split": KEY + s, "card": "CARD-1", "reason": "r"} for s in waived
        ],
    }


def found(gaps: list[Any], code: str | None = None) -> set[str]:
    return {g.subject for g in gaps if code in (None, g.code)}


def test_every_split_is_required_and_a_waiver_or_a_covering_cell_clears_it(
    tmp_path: Path,
) -> None:
    derived, files = load_splits(axes_file(tmp_path))
    assert files == {"app.py"}
    gaps = check_splits(design("at_max"), derived)
    assert found(gaps, "G8_SPLIT_MISSING") == {KEY + s for s in EVERY[1:]}
    assert check_splits(design(waived=EVERY), derived) == []
    assert check_splits(design(*EVERY, scope="regression"), derived) == []
    assert (
        len(check_splits(design(*EVERY, scope="hold"), derived)) == 5
    )  # hold covers nothing


def test_dangling_references_in_any_cell_and_the_scope_prefix(tmp_path: Path) -> None:
    derived, _ = load_splits(axes_file(tmp_path, APP + OTHER))
    assert found(check_splits(design(*EVERY), derived)) == {
        f"app.py::length_split:U.n#{s}" for s in EVERY
    }
    assert check_splits(design(*EVERY), derived, ("elsewhere/",)) == []
    for scope in ("in", "hold"):  # the scope filters requirements, never references
        gaps = check_splits(
            design(*EVERY, "nope", scope=scope), derived, ("elsewhere/",)
        )
        assert found(gaps) == {KEY + "nope"} and gaps[0].code == "G7_DANGLING_REF"


def test_split_references_round_trip_through_the_schema() -> None:
    cell = {
        "id": "C-1",
        "req": "REQ-1",
        "axis": "boundary",
        "platform": "web",
        "source": "observed",
        "scope": "in",
        "risk": "R1",
    }
    doc = {
        "apiVersion": "ai-qa/qa-design/v1",
        "feature": "f",
        "requirements": [{"id": "REQ-1", "ac": ["AC1"], "scope": "in", "risk": "R1"}],
        "matrix": [{**cell, "splits": ["a b/m.py::length_split:M.t#at_max"]}],
        "budget": RISKS,
        "waivers": [
            {
                "split": "a b/m.py::length_split:M.t#over_max",
                "card": "CARD-1",
                "reason": "r",
            }
        ],
    }
    validate("qa-design", doc)
    for bad in (
        {"split": "x::length_split:M.t#nope"},
        {"split": "x::length_split:M.t#at_max", "cell": "C-1"},
    ):
        with pytest.raises(InvalidInput):
            validate(
                "qa-design",
                {**doc, "waivers": [{**bad, "card": "CARD-1", "reason": "r"}]},
            )


def test_cli_reports_the_gap_and_rejects_bad_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "spec.json").write_text(
        json.dumps(
            {
                "apiVersion": "ai-qa/spec/v1",
                "feature": "f",
                "acs": [{"id": "AC1", "scope": "in", "text": "t"}],
            }
        )
    )
    cell = {
        "id": "C-1",
        "req": "REQ-1",
        "axis": "boundary",
        "platform": "web",
        "source": "normative",
        "expected": "x",
    }
    base = {
        "apiVersion": "ai-qa/qa-design/v1",
        "feature": "f",
        "requirements": [{"id": "REQ-1", "ac": ["AC1"], "scope": "in", "risk": "R1"}],
        "matrix": [{**cell, "scope": "in", "risk": "R1", "splits": [KEY + "at_max"]}],
        "budget": RISKS,
    }
    (tmp_path / "design.yaml").write_text(json.dumps(base))
    axes = axes_file(tmp_path, APP + OTHER)
    argv = [
        "design",
        "check",
        "--spec",
        str(tmp_path / "spec.json"),
        "--design",
        str(tmp_path / "design.yaml"),
    ]
    with_axes = [*argv, "--axes", str(axes)]
    assert main(argv) == 0  # no --axes: nothing to compare
    capsys.readouterr()
    assert main(with_axes) == 1
    assert {g["code"] for g in json.loads(capsys.readouterr().out)["gaps"]} == {
        "G8_SPLIT_MISSING"
    }
    assert (
        main([*with_axes, "--axes-scope", "./app.py"]) == 1
    )  # a leading ./ is ignored
    base["matrix"][0]["splits"] = [KEY + s for s in EVERY]
    (tmp_path / "design.yaml").write_text(json.dumps(base))
    assert main([*with_axes, "--axes-scope", "app.py"]) == 1  # U.n is under app.py too
    assert main(with_axes) == 1
    for bad in (
        ["--axes-scope", "typo/"],
        ["--axes-scope", "app.py", "--axes-scope", "typo/"],
    ):
        assert main([*with_axes, *bad]) == 2
    assert main([*argv, "--axes-scope", "app.py"]) == 2  # a scope without --axes
    good = json.loads(axes.read_text())
    cell = {"kind": "length_split", "key": KEY + "at_max", "file": "app.py"}
    for bad in (
        [],
        {**good, "apiVersion": "x"},
        {**good, "axes": "unknown"},
        {**good, "cells": [None]},
        {**good, "cells": [{"key": "k", "file": "f"}]},
        {**good, "cells": [{**cell, "key": "x"}]},
    ):
        axes.write_text(json.dumps(bad))
        assert main(with_axes) == 2
    axes.unlink()
    assert main(with_axes) == 2
