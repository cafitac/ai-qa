from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from aiqa.axes import extract_axes
from aiqa.cli import main

FIXTURES = Path(__file__).parent / "fixtures" / "axes"
SCHEMA = Path(__file__).parent.parent / "schemas" / "qa-design.schema.json"


def cells(repo: Path) -> set[tuple[str, str, str]]:
    out = extract_axes(repo)
    return {(c["axis"], c["kind"], c["subject"]) for c in out["cells"]}


def test_fastapi_fixture_yields_every_observed_axis() -> None:
    out = extract_axes(FIXTURES / "fastapi_app")
    ship, dispatch = (f"POST /orders/{{order_id}}/{n}" for n in ("ship", "dispatch"))
    assert cells(FIXTURES / "fastapi_app") == {
        ("flow", "route", ship),
        ("flow", "route", dispatch),
        ("permission", "role_check", f"{ship} requires admin"),
        ("permission", "role_check", f"{dispatch} requires admin"),
        ("permission", "role_check", f"{dispatch} requires ops"),
        ("empty_error", "error_response", f"{ship} 404"),
        ("empty_error", "error_response", f"{dispatch} 404"),
        ("state", "enum", "OrderState"),
        ("state", "transition", "Payments.TRANSITIONS: NEW -> PAID"),
        ("validation", "validator", "OrderCreate.not_blank"),
        ("validation", "constraint", "OrderCreate.title"),
        ("flag", "feature_flag", "SHIP_MODE"),
        ("flag", "feature_flag", "NOTIFIER_URL"),
    }
    detail = {c["kind"]: c["detail"] for c in out["cells"] if "detail" in c}
    assert detail["enum"] == {"values": ["NEW", "PAID", "SHIPPED"]}


def test_cells_match_the_matrix_cell_shape() -> None:
    schema = json.loads(SCHEMA.read_text())["properties"]["matrix"]["items"]
    out = extract_axes(FIXTURES / "fastapi_app")["cells"]
    for cell in out:
        assert cell["axis"] in schema["properties"]["axis"]["enum"]
        assert (cell["source"], cell["platform"]) == ("observed", "web")
    assert len({c["key"] for c in out}) == len(out)
    assert "app.boom" not in sys.modules  # the target repo is never imported


def test_unsupported_stack_is_unknown_not_an_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["axes", str(FIXTURES / "plain_repo")]) == 0
    out = json.loads(capsys.readouterr().out)
    assert (out["axes"], out["cells"], out["extractor"]) == ("unknown", [], None)
    assert main(["axes", str(FIXTURES / "absent")]) == 2


def test_tests_broken_files_and_symlinks_are_skipped(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "client.py").write_text("from fastapi import FastAPI\n")
    (tmp_path / "broken.py").write_text("def (:\n")
    assert extract_axes(tmp_path)["axes"] == "unknown"
    (tmp_path / "app.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n@app.get('/x')\ndef x(): ...\n"
    )
    (tmp_path / "link.py").symlink_to(tmp_path / "app.py")
    assert cells(tmp_path) == {("flow", "route", "GET /x")}


def test_aliases_scopes_and_unsupported_values(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text(
        "from fastapi import FastAPI as API, HTTPException, status\n"
        "from enum import Enum\nfrom pydantic import Field\napp = API()\n"
        "class A:\n class S(Enum):\n  NEW = 1\n  _ignore_ = 'x'\n"
        "class B:\n class S(Enum):\n  OLD = 2\n"
        f"class M:\n n: int = Field(le=1e999, ge=1, gt=1{'0' * 400})\n"
        "class V:\n @root_validator\n def r(cls, v): ...\n"
        "from hooks import hooks\n@hooks.get('created')\ndef h(): ...\n"
        "reg = {}\n@reg.get('y')\ndef y(): ...\n@app.get(path='/x')\n"
        "def x():\n raise HTTPException(status.HTTP_400_BAD_REQUEST + 1)\n"
    )
    by = {
        (c["kind"], c["subject"]): c.get("detail")
        for c in extract_axes(tmp_path)["cells"]
    }
    assert by[("enum", "A.S")] == {"values": ["NEW"]} and ("enum", "B.S") in by
    assert by[("constraint", "M.n")] == {"ge": 1} and ("route", "GET /x") in by
    assert by[("error_response", "GET /x None")] == {"status": None}
    assert ("route", "GET y") not in by and ("route", "GET created") not in by
    assert ("validator", "V.r") in by
