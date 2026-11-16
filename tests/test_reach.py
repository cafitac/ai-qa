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


def typed(tmp_path: Path, *events: str) -> list[str]:
    log = tmp_path / "agent.jsonl"
    log.write_text("not json\n" + "\n".join(events) + "\n")
    return reach.typed_inputs(log)


def classify(texts, defect):
    inputs = [(f"s{n}", t) for n, t in enumerate(texts)]
    return reach.reach(
        SPEC, inputs, (notes_app(), "https://b"), (notes_app(defect), "https://m")
    )


def test_only_submitted_text_counts(tmp_path):
    submit = [tool("type", target="e1", text="by key"), tool("press_key", key="Tab")]
    form = [
        tool("type", target="title", text="two"),
        tool("type", target="body", text="fields "),
    ]
    got = typed(
        tmp_path,
        tool("navigate", url="u"),
        tool("type", target="e1", text="  sent  "),
        tool("click", target="e2"),
        tool("type", target="e1", text="abandoned"),
        tool("navigate", url="u"),
        *submit,
        tool("press_key", key="Enter"),
        tool("type", target="e1", text="with submit", submit=True),
        tool("snapshot"),
        tool("type", target="e1", text="back"),
        tool("navigate_back"),
        tool("click", target="e2"),
        *form,
        tool("type", target="body", text="more", slowly=True),
        tool("click", target="save"),
        tool("type", target="e1", text="never submitted"),
    )
    assert got == ["  sent  ", "by key", "with submit", "two", "fields more"]


def test_unreadable_events_are_skipped_and_jsonl_splits_on_newlines_only(tmp_path):
    junk = ['{"message": {"content": "text"}}', "[1]", "7", tool("type", text=5)]
    assert typed(tmp_path, *junk, tool("click")) == []
    text = "a\u2028b\x85c"
    assert typed(
        tmp_path, tool("type", text=text), tool("click"), tool("type", text="z")
    ) == [text]


def test_ascii_set_is_unreached_and_matching_inputs_are_reached():
    ascii_set = ["note", "x" * 500, "x" * 501, "a"]
    assert [classify(ascii_set, d)["classification"] for d in ("bytes", "fold")] == [
        "UNREACHED"
    ] * 2
    assert classify(["x", "한" * 200], "bytes")["classification"] == "REACHED"
    folded = classify(["a" * 200 + "  " + "b" * 299 + " "], "fold")  # 500 once folded
    assert folded["classification"] == "REACHED" and folded["inputs"][0]["reached"]
    assert classify(["a\n\nb"], "fold")["classification"] == "REACHED"  # stored text


@pytest.mark.parametrize(
    ("base", "mutant", "answer"),
    [
        (notes_app(), lambda *_: (0, None), "INCONCLUSIVE"),  # no answer
        (lambda *_: (429, None),) * 2 + ("INCONCLUSIVE",),  # rate limited
        (lambda *_: (422, {"text": "x"}),) * 2 + ("INCONCLUSIVE",),  # both reject
        (lambda *_: (201, None),) * 2 + ("INCONCLUSIVE",),  # nothing to compare
    ],
)
def test_unreached_needs_both_sides_to_answer_and_something_compared(
    base, mutant, answer
):
    assert (
        reach.reach(SPEC, [("s", "x")], (base, "b"), (mutant, "m"))["classification"]
        == answer
    )
    assert classify([], "bytes")["classification"] == "NO_INPUT"


def test_one_request_per_distinct_text_across_scenarios_and_attempts():
    seen = []

    def http(method, url, body):
        seen.append(body["text"])
        return 201, {"text": body["text"]}

    pairs = [("a", "x"), ("a", "y"), ("b", "x"), ("b", " x\ufeff"), ("b", "\x1fy")]
    out = reach.reach(SPEC, pairs, (http, ""), (http, ""))
    # JS trim drops U+FEFF but not U+001F
    assert seen == ["x", "x", "y", "y", "\x1fy", "\x1fy"]
    assert out["classification"] == "UNREACHED"
    assert [r["scenario"] for r in out["inputs"]] == ["a", "a", "b"]


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
    reach.reach(SPEC, [("s", " y ")], (http, ""), (http, ""))
    assert seen[::2] == [{"a": [" y ", 1], "b": "< y >"}, {"text": "y"}]


@pytest.mark.parametrize(
    "bad",
    [
        {"trim": None},
        {"compare": "text"},
        {"compare": [1]},
        {"request": {**SPEC["request"], "json": {"text": "fixed"}}},
    ],
)
def test_a_replay_that_cannot_differ_is_refused(bad):
    with pytest.raises(InvalidInput):
        reach.reach({**SPEC, **bad}, [("s", "x")], (notes_app(), ""), (notes_app(), ""))
