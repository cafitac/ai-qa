from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from aiqa.axes import extract_axes
from aiqa.axes.fastapi_extractor import LENGTH_SPLITS
from aiqa.cli import main
from aiqa.design import check_splits, load_splits

APP = (
    "from fastapi import FastAPI\nfrom pydantic import BaseModel, Field\n"
    "app = FastAPI()\n"
    "class Note(BaseModel):\n"
    "    text: str = Field(min_length=1, max_length=500)\n"
    "    tags: list[str] = Field(max_length=3)\n"
    "    code: int = Field(max_length=2)\n"
    "    memo: str | None = Field(default=None, min_length=1)\n"
)
KEY = "app.py::length_split:Note.text#"
SPEC = {"acs": [{"id": "AC1", "scope": "in", "text": "Text is stored"}]}
NO_CHANGE = {"acs": [{"id": "AC1", "scope": "in", "text": "Stored text: no change"}]}


def axes(tmp_path: Path) -> dict:
    (tmp_path / "app.py").write_text(APP)
    return extract_axes(tmp_path)


def splits(tmp_path: Path) -> dict[str, str]:
    (tmp_path / "axes.json").write_text(json.dumps(axes(tmp_path)))
    return load_splits(tmp_path / "axes.json")


def design(*splits: str, waived: tuple[str, ...] = (), scope: str = "in") -> dict:
    return {
        "matrix": [{"id": "C-1", "scope": scope, "splits": [KEY + s for s in splits]}],
        "waivers": [
            {"split": KEY + s, "card": "CARD-1", "reason": "r"} for s in waived
        ],
    }


def test_only_string_max_length_derives_the_five_splits(tmp_path: Path) -> None:
    cells = [c for c in axes(tmp_path)["cells"] if c["kind"] == "length_split"]
    assert {c["key"] for c in cells} == {KEY + s for s in LENGTH_SPLITS}
    assert {c["axis"] for c in cells} == {"boundary"}
    assert all(c["detail"]["max_length"] == 500 for c in cells)


def test_missing_splits_are_gaps_and_whitespace_needs_a_no_change_ac(
    tmp_path: Path,
) -> None:
    found = splits(tmp_path)
    gaps = check_splits(SPEC, design("at_max"), found)
    assert {g.subject for g in gaps} == {
        KEY + s for s in ("over_max", "multibyte_near_max", "normalized_fits")
    }
    assert {g.code for g in gaps} == {"G8_SPLIT_MISSING"}
    gaps = check_splits(NO_CHANGE, design("at_max"), found)
    assert KEY + "whitespace_preserved" in {g.subject for g in gaps}


def test_waiver_covers_but_a_hold_cell_does_not(tmp_path: Path) -> None:
    found = splits(tmp_path)
    every = tuple(LENGTH_SPLITS)
    assert check_splits(NO_CHANGE, design(waived=every), found) == []
    assert check_splits(NO_CHANGE, design(*every), found) == []
    assert len(check_splits(NO_CHANGE, design(*every, scope="hold"), found)) == 5


def test_unknown_split_reference_is_dangling(tmp_path: Path) -> None:
    found = splits(tmp_path)
    bad = design(*LENGTH_SPLITS, waived=("nope",))
    assert [(g.code, g.subject) for g in check_splits(SPEC, bad, found)] == [
        ("G7_DANGLING_REF", KEY + "nope")
    ]


def test_cli_axes_option_reports_the_gap(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = {"apiVersion": "ai-qa/spec/v1", "feature": "f", **SPEC}
    base = {
        "apiVersion": "ai-qa/qa-design/v1",
        "feature": "f",
        "requirements": [{"id": "REQ-1", "ac": ["AC1"], "scope": "in", "risk": "R1"}],
        "matrix": [
            {
                "id": "C-1",
                "req": "REQ-1",
                "axis": "boundary",
                "platform": "web",
                "source": "normative",
                "expected": "x",
                "scope": "in",
                "risk": "R1",
                "splits": [KEY + "at_max"],
            }
        ],
        "budget": {
            r: {"min": 0, "minNegative": 0, "minBoundary": 0, "nonHappyShare": 0}
            for r in ("R1", "R2", "R3", "R4")
        },
    }
    (tmp_path / "spec.json").write_text(json.dumps(spec))
    (tmp_path / "design.yaml").write_text(json.dumps(base))
    (tmp_path / "axes.json").write_text(json.dumps(axes(tmp_path)))
    argv = ["design", "check", "--spec", str(tmp_path / "spec.json")]
    argv += ["--design", str(tmp_path / "design.yaml")]
    assert main(argv) == 0  # no --axes: nothing to compare
    capsys.readouterr()
    assert main([*argv, "--axes", str(tmp_path / "axes.json")]) == 1
    out = json.loads(capsys.readouterr().out)
    assert {g["code"] for g in out["gaps"]} == {"G8_SPLIT_MISSING"}
    full = copy.deepcopy(base)
    full["matrix"][0]["splits"] = [KEY + s for s in LENGTH_SPLITS]
    (tmp_path / "design.yaml").write_text(json.dumps(full))
    assert main([*argv, "--axes", str(tmp_path / "axes.json")]) == 0
    (tmp_path / "axes.json").write_text("[]")
    assert main([*argv, "--axes", str(tmp_path / "axes.json")]) == 2
