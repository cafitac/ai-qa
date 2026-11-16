import json
from pathlib import Path

import pytest

from aiqa import reach
from aiqa.contracts import InvalidInput

SPEC = {
    "apiVersion": "ai-qa/reach/v1",
    "service": "backend",
    "request": {"method": "POST", "path": "/api/notes", "json": {"text": "{input}"}},
    "trim": True,
    "compare": ["text"],
}


def notes_app(defect=None):
    """The notes API's validator with one optional seeded defect (as in the missed-mutant analysis)."""

    def http(method, url, body):
        text = body["text"]
        if defect == "bytes" and len(text.encode()) > 500:
            return 422, None
        if defect == "fold":
            text = " ".join(text.split())
        return (201, {"text": text}) if 1 <= len(text) <= 500 else (422, None)

    return http


def tool(name, **args):
    block = {
        "type": "tool_use",
        "id": "t",
        "name": f"mcp__playwright__browser_{name}",
        "input": args,
    }
    return json.dumps(
        {"type": "assistant", "message": {"content": [block]}}, ensure_ascii=False
    )


def write_run(root: Path, *scenarios) -> Path:
    """A baseline run directory whose agent logs a fake agent left behind; `scenarios` are (id, [events])."""
    for sid, events in scenarios:
        log = root / "scenarios" / f"frontend__{sid}" / "attempt-1" / "agent.jsonl"
        log.parent.mkdir(parents=True)
        log.write_text("not json\n" + "\n".join(events) + "\n")
    return root


def classify(texts, defect):
    inputs = [(f"s{n}", t) for n, t in enumerate(texts)]
    return reach.reach(
        SPEC, inputs, (notes_app(), "https://b"), (notes_app(defect), "https://m")
    )


def test_only_submitted_text_counts(tmp_path):
    run = write_run(
        tmp_path,
        (
            "a",
            [
                tool("navigate", url="u"),
                tool("type", target="e1", text="  sent  "),
                tool("click", target="e2"),
                tool("type", target="e1", text="abandoned"),
                tool("navigate", url="u"),
                tool("type", target="e1", text="by key"),
                tool("press_key", key="Tab"),
                tool("press_key", key="Enter"),
                tool("type", target="e1", text="with submit", submit=True),
                tool("snapshot"),
                tool("type", target="e1", text="back"),
                tool("navigate_back"),
                tool("click", target="e2"),
                tool("type", target="e1", text="never submitted"),
            ],
        ),
        ("b", ['{"message": {"content": "text"}}', "[1]", "7", tool("type", text=5)]),
        (
            "c",
            [tool("type", text="a\u2028b\x85c"), tool("click"), tool("type", text="z")],
        ),
    )
    logs = dict(reach.agent_logs(run))
    assert list(logs) == ["frontend/a", "frontend/b", "frontend/c"]
    assert reach.typed_inputs(logs["frontend/c"]) == [
        "a\u2028b\x85c"
    ]  # JSONL splits on newlines only
    assert reach.typed_inputs(logs["frontend/a"]) == [
        "  sent  ",
        "by key",
        "with submit",
    ]
    assert reach.typed_inputs(logs["frontend/b"]) == []


def test_ascii_set_is_unreached_and_matching_inputs_are_reached():
    ascii_set = ["note", "x" * 500, "x" * 501, "a"]
    assert [classify(ascii_set, d)["classification"] for d in ("bytes", "fold")] == [
        "UNREACHED"
    ] * 2
    assert classify(["한" * 200], "bytes")["classification"] == "REACHED"
    folded = classify(
        ["a" * 200 + "  " + "b" * 299 + " "], "fold"
    )  # 501 raw once trimmed, 500 folded
    assert folded["classification"] == "REACHED" and folded["inputs"][0]["reached"]
    assert (
        classify(["a\n\nb"], "fold")["classification"] == "REACHED"
    )  # only the stored text differs


def test_no_input_no_answer_and_unreached_need_every_input_answered():
    assert classify([], "bytes")["classification"] == "NO_INPUT"
    down = lambda *_: (0, None)
    out = reach.reach(SPEC, [("s", "x")], (notes_app(), "b"), (down, "m"))
    assert out["classification"] == "INCONCLUSIVE" and not out["inputs"][0]["answered"]
    limited = lambda *_: (429, None)
    assert reach.reach(SPEC, [("s", "x")], (limited, "b"), (limited, "m"))[
        "classification"
    ] == ("INCONCLUSIVE")
    assert classify(["x", "한" * 200], "bytes")["classification"] == "REACHED"
    assert classify(["x" * 501, "한" * 200], "bytes")["classification"] == "REACHED"


def test_a_replay_both_sides_reject_proves_nothing():
    rejects = lambda *_: (422, {"text": "x"})
    out = reach.reach(SPEC, [("s", "x")], (rejects, "b"), (rejects, "m"))
    assert out["classification"] == "INCONCLUSIVE" and out["inputs"][0]["answered"]


def test_one_request_per_distinct_text_across_scenarios_and_attempts():
    seen = []

    def http(method, url, body):
        seen.append(body["text"])
        return 201, {"text": body["text"]}

    pairs = [("a", "x"), ("a", "y"), ("b", "x")]
    out = reach.reach(SPEC, pairs, (http, ""), (http, ""))
    assert seen == ["x", "x", "y", "y"] and out["classification"] == "UNREACHED"
    assert [r["scenario"] for r in out["inputs"]] == ["a", "a"]


def test_trim_and_placeholder_substitution():
    seen = []

    def http(method, url, body):
        seen.append(body)
        return 201, {"text": "t"}

    spec = {
        **SPEC,
        "trim": False,
        "request": {**SPEC["request"], "json": {"a": ["{input}", 1], "b": "<{input}>"}},
    }
    reach.reach(spec, [("s", " y ")], (http, ""), (http, ""))
    assert seen[0] == {"a": [" y ", 1], "b": "< y >"}
    reach.reach(SPEC, [("s", " y ")], (http, ""), (http, ""))
    assert seen[2] == {"text": "y"}


@pytest.mark.parametrize(
    "bad",
    [
        {"trim": None},
        {"compare": []},
        {"request": {**SPEC["request"], "json": {"text": "fixed"}}},
    ],
)
def test_a_replay_that_cannot_differ_is_refused(bad):
    with pytest.raises(InvalidInput):
        reach.reach({**SPEC, **bad}, [("s", "x")], (notes_app(), ""), (notes_app(), ""))
