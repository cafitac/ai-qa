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
KEY = "app.py::length_split:Note.text#"
EVERY = tuple(LENGTH_SPLITS)
SPEC = {"acs": [{"id": "AC1", "scope": "in", "text": "Text is stored"}]}
RISKS = {
    r: dict.fromkeys(("min", "minNegative", "minBoundary", "nonHappyShare"), 0)
    for r in ("R1", "R2", "R3", "R4")
}


def splits(tmp_path: Path, source: str = APP) -> dict[str, tuple[str, str]]:
    (tmp_path / "app.py").write_text(source)
    (tmp_path / "axes.json").write_text(json.dumps(extract_axes(tmp_path)))
    return load_splits(tmp_path / "axes.json")


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


def test_missing_splits_are_gaps_and_a_waiver_or_a_covering_cell_clears_them(
    tmp_path: Path,
) -> None:
    derived = splits(tmp_path)
    gaps = check_splits(SPEC, design("at_max"), derived)
    assert found(gaps, "G8_SPLIT_MISSING") == {KEY + s for s in EVERY[1:4]}
    assert check_splits(SPEC, design(waived=EVERY), derived) == []
    assert check_splits(SPEC, design(*EVERY, scope="regression"), derived) == []
    assert (
        len(check_splits(SPEC, design(*EVERY, scope="hold"), derived)) == 4
    )  # hold covers nothing


@pytest.mark.parametrize(
    ("text", "required"),
    [
        ("The listed text is exactly the submitted text (no change)", True),
        ("The saved text is identical to the submitted text, spaces included", True),
        ("저장된 메모는 입력한 대로 그대로 표시된다", True),
        ("The order count remains unchanged after a refusal", False),
        ("The text is not stored verbatim", False),
    ],
)
def test_whitespace_preserved_needs_a_no_change_ac_about_text(
    tmp_path: Path, text: str, required: bool
) -> None:
    derived, key = splits(tmp_path), KEY + "whitespace_preserved"
    for scope in ("in", "excluded"):
        spec = {"acs": [{"id": "AC1", "scope": scope, "text": text}]}
        assert (key in found(check_splits(spec, design("at_max"), derived))) is (
            required and scope == "in"
        )


def test_dangling_references_in_any_cell_and_the_scope_prefix(tmp_path: Path) -> None:
    derived = splits(
        tmp_path, APP + "class U(BaseModel):\n    n: str = Field(max_length=9)\n"
    )
    assert found(check_splits(SPEC, design(*EVERY), derived)) == {
        f"app.py::length_split:U.n#{s}" for s in EVERY[:4]
    }
    assert check_splits(SPEC, design(*EVERY), derived, ("elsewhere/",)) == []
    for scope in ("in", "hold"):  # the scope filters requirements, never references
        gaps = check_splits(
            SPEC, design(*EVERY, "nope", scope=scope), derived, ("elsewhere/",)
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


def test_cli_reports_the_gap_and_rejects_bad_axes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "spec.json").write_text(
        json.dumps({"apiVersion": "ai-qa/spec/v1", "feature": "f", **SPEC})
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
    splits(tmp_path)
    argv = [
        "design",
        "check",
        "--spec",
        str(tmp_path / "spec.json"),
        "--design",
        str(tmp_path / "design.yaml"),
    ]
    with_axes = [*argv, "--axes", str(tmp_path / "axes.json")]
    assert main(argv) == 0  # no --axes: nothing to compare
    capsys.readouterr()
    assert main(with_axes) == 1
    assert {g["code"] for g in json.loads(capsys.readouterr().out)["gaps"]} == {
        "G8_SPLIT_MISSING"
    }
    assert main([*with_axes, "--axes-scope", "elsewhere/"]) == 0
    base["matrix"][0]["splits"] = [KEY + s for s in EVERY]
    (tmp_path / "design.yaml").write_text(json.dumps(base))
    assert main(with_axes) == 0
    good = json.loads((tmp_path / "axes.json").read_text())
    for bad in (
        [],
        {**good, "apiVersion": "x"},
        {**good, "axes": "unknown"},
        {**good, "cells": [None]},
    ):
        (tmp_path / "axes.json").write_text(json.dumps(bad))
        assert main(with_axes) == 2
    (tmp_path / "axes.json").unlink()
    assert main(with_axes) == 2
