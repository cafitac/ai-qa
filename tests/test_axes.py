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
        (
            "state",
            "transition",
            "Payments.TRANSITIONS: OrderState.NEW -> OrderState.PAID",
        ),
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
        "from fastapi import FastAPI as API, HTTPException, status, Depends, APIRouter\n"
        "from enum import Enum\nfrom pydantic import Field\napp = API()\n"
        "class A:\n class S(Enum):\n  NEW = 1\n  _ignore_ = 'x'\n"
        "class B:\n class S(Enum):\n  OLD = 2\n"
        f"class M:\n n: int = Field(le=1e999, ge=1, gt=1{'0' * 400}, lt=-9223372036854775808)\n"
        "class V:\n @root_validator\n def r(cls, v): ...\n"
        "PX = '/p'\npx = APIRouter(prefix=PX)\nra = APIRouter()\nrb = APIRouter()\n"
        "@px.get('/q', dependencies=[Depends(require_role(role='admin'))])\ndef q(): ...\n"
        "@ra.get('/')\ndef ra_(): raise HTTPException(403)\n"
        "@rb.get('/')\ndef rb_(): raise HTTPException(404)\n"
        "import os\nos.getenv(key='ENABLE_X')\n"
        "TRANSITIONS = {A.N: [A.D], B.N: [B.D]}\n"
        "from hooks import hooks\n@hooks.get('created')\ndef h(): ...\n"
        "reg = {}\n@reg.get('y')\ndef y(): ...\n@app.get(path='/x')\n"
        "def x():\n raise HTTPException(status.HTTP_400_BAD_REQUEST + 1)\n"
    )
    out = extract_axes(tmp_path)["cells"]
    by = {(c["kind"], c["subject"]): c.get("detail") for c in out}
    assert by[("enum", "A.S")] == {"values": ["NEW"]} and ("enum", "B.S") in by
    assert (
        by[("constraint", "M.n")] == {"ge": 1, "lt": -(2**63)}
        and ("route", "GET /x") in by
    )
    assert by[("error_response", "GET /x None")] == {"status": None}
    assert ("route", "GET y") not in by and ("route", "GET created") not in by
    assert ("validator", "V.r") in by and ("feature_flag", "ENABLE_X") in by
    assert by[("route", "GET /q")] == {"prefix": "unresolved"}
    assert ("role_check", "GET /q requires admin") in by
    assert sum(c["subject"] == "GET /" for c in out) == 2  # same path, two routers
    assert {("error_response", "GET / 403"), ("error_response", "GET / 404")} <= set(by)
    assert sum(c["kind"] == "transition" for c in out) == 2


def test_api_route_scopes_dup_keys_limits_opts_and_status_bounds(
    tmp_path: Path,
) -> None:
    (tmp_path / "app.py").write_text(
        "from fastapi import FastAPI, APIRouter, Security, HTTPException\n"
        "from pydantic import Field\napp = FastAPI()\nopts = {}\nr = APIRouter(**opts)\n"
        "@app.api_route('/m', methods=['get', 'POST'],\n"
        "               dependencies=[Security(get_user, scopes=['a:read'])])\n"
        "def m(): raise HTTPException(1180591620717411303424)\n"
        "@r.get('/o')\ndef o(): ...\n"
        "app2 = FastAPI(**opts)\n@app2.get('/f')\ndef f(): ...\n"
        "@app.api_route('/n', methods=None,\n"
        "               dependencies=[Security(get_user, scopes=['x']), Security(get_user, scopes=['y'])])\n"
        "def n(): ...\n"
        "@app.api_route('/k', **{'methods': ['POST']})\ndef k(): ...\n"
        "@app.api_route('/d')\ndef d(): ...\n"
        "class M:\n n: int = Field(multiple_of=5, max_digits=7, decimal_places=2)\n"
        " s: str = Field(regex='^a', min_items=1, max_items=2)\n"
        "TRANSITIONS = {'a': ['x'], 'a': ['y'], 'b': ['z'], nx(): ['p'], nx(): ['q'], S.n: ['r'], S.n: ['s'], None: ['o'], None: ['n']}\n"
    )
    out = extract_axes(tmp_path)["cells"]
    by = {(c["kind"], c["subject"]): c.get("detail") for c in out}
    assert {("route", "GET /m"), ("route", "POST /m")} <= set(by)
    assert by[("role_check", "POST /m requires get_user")] == {"scopes": ["a:read"]}
    assert by[("error_response", "GET /m None")] == {"status": None}
    assert by[("route", "GET /o")] == {"prefix": "unresolved"}
    assert by[("constraint", "M.n")] == {
        "multiple_of": 5,
        "max_digits": 7,
        "decimal_places": 2,
    }
    assert by[("constraint", "M.s")] == {"regex": "^a", "min_items": 1, "max_items": 2}
    edges = {s for k, s in by if k == "transition"}
    assert edges == {f"TRANSITIONS: {e}" for e in ("'a' -> 'y'", "'b' -> 'z'")} | {
        "TRANSITIONS: nx() -> 'p'",
        "TRANSITIONS: nx() -> 'q'",
        "TRANSITIONS: None -> 'n'",
        "TRANSITIONS: S.n -> 'r'",
        "TRANSITIONS: S.n -> 's'",
    }
    assert ("route", "GET /f") in by and by[("route", "GET /f")] is None  # no prefix
    assert by[("role_check", "GET /n requires get_user")] == {"scopes": ["x", "y"]}
    assert not any(s.endswith(" /k") for k, s in by if k == "route")
    assert ("route", "GET /d") in by and ("route", "POST /d") not in by
