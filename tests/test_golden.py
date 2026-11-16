from __future__ import annotations

import copy
from typing import Any

import pytest

from aiqa.contracts import InvalidInput, validate

ENTRY: dict[str, Any] = {
    "id": "golden-1",
    "pattern": "form-validation",
    "scenario": {
        "kind": "happy",
        "title": "Add a note",
        "start": "/notes",
        "steps": ["Type x", "Save"],
        "expect": ["x is listed first"],
    },
    "source": {"feature": "f", "runSha": "a" * 64, "scenario": "web/add-note"},
}
DOC: dict[str, Any] = {
    "apiVersion": "ai-qa/golden/v1",
    "project": "p",
    "entries": [ENTRY],
}


def test_the_entry_qa_golden_writes_is_valid() -> None:
    assert validate("golden", DOC) == DOC


@pytest.mark.parametrize(
    "path,value",
    [
        (("pattern",), "forms"),
        (("id",), "add-note"),
        (("scenario", "ac"), ["AC1"]),
        (("scenario", "steps"), []),
        (("source", "runSha"), "A" * 64),
        (("source", "scenario"), "add-note"),
    ],
)
def test_entries_outside_the_contract_are_refused(
    path: tuple[str, ...], value: object
) -> None:
    doc = copy.deepcopy(DOC)
    node = doc["entries"][0]
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    with pytest.raises(InvalidInput):
        validate("golden", doc)
