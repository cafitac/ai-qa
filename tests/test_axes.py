from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from aiqa.axes import extract_axes
from aiqa.cli import main

FIXTURES = Path(__file__).parent / "fixtures" / "axes"
SCHEMA = Path(__file__).parent.parent / "schemas" / "qa-design.schema.json"
SHIP = "POST /orders/{order_id}/ship"


def cells(repo: Path) -> set[tuple[str, str, str]]:
    out = extract_axes(repo)
    return {(c["axis"], c["kind"], c["subject"]) for c in out["cells"]}


def test_fastapi_fixture_yields_every_observed_axis() -> None:
    out = extract_axes(FIXTURES / "fastapi_app")
    assert (out["axes"], out["extractor"]) == ("observed", "fastapi")
    assert cells(FIXTURES / "fastapi_app") == {
        ("flow", "route", "POST /orders"),
        ("flow", "route", SHIP),
        ("permission", "role_check", "POST /orders requires get_current_user"),
        ("permission", "role_check", f"{SHIP} requires admin"),
        ("state", "enum", "OrderState"),
        ("state", "transition", "TRANSITIONS: NEW -> PAID"),
        ("state", "transition", "TRANSITIONS: PAID -> SHIPPED"),
        ("validation", "validator", "OrderCreate.not_blank"),
        ("validation", "constraint", "OrderCreate.title"),
        ("flag", "feature_flag", "SHIPPING_ENABLED"),
        ("flag", "feature_flag", "NOTIFIER_URL"),
        ("empty_error", "error_response", f"{SHIP} 404"),
    }
    by_kind = {c["kind"]: c for c in out["cells"]}
    assert by_kind["enum"]["detail"]["values"] == ["NEW", "PAID", "SHIPPED"]
    assert by_kind["constraint"]["detail"] == {"min_length": 1, "max_length": 80}
    assert by_kind["error_response"]["detail"]["status"] == 404
    assert by_kind["enum"]["file"] == "app/main.py"


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


def test_missing_path_is_invalid_input(tmp_path: Path) -> None:
    assert main(["axes", str(tmp_path / "absent")]) == 2


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
