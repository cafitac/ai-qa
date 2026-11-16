import json
from contextlib import nullcontext

import pytest
import yaml
from test_mutants import NOW, env
from test_reach import SPEC, notes_app, tool

from aiqa import mutants
from aiqa.cli import main as cli_main
from aiqa.contracts import Config


def write_run(root, *scenarios):
    for sid, events in scenarios:
        log = root / "scenarios" / f"frontend__{sid}" / "attempt-1" / "agent.jsonl"
        log.parent.mkdir(parents=True)
        log.write_text("\n".join(events) + "\n")
    return root


def run_cli(tmp_path, monkeypatch, run_dir, spec=SPEC, ready="READY", args=()):
    apps = {"base.test": notes_app(), "mut.test": notes_app("bytes")}
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mutants.Config, "load", lambda path=None: Config())
    http = lambda m, u, b: apps[u.split("/")[2]](m, "/" + u.split("/", 3)[3], b)
    monkeypatch.setattr(mutants, "playwright_http", lambda *_: nullcontext(http))
    (tmp_path / "replay.yaml").write_text(yaml.safe_dump(spec))
    for name, desc in (
        ("b.json", env("base", "main", "base.test")),
        ("m.json", env("mut", "m", "mut.test", ready)),
    ):
        (tmp_path / name).write_text(json.dumps(desc.data))
    argv = ["mutant", "reach", "--replay", "replay.yaml", "--baseline", "b.json"]
    return cli_main(
        [*argv, "--mutant", "m.json", "--run", str(run_dir), *args], clock=lambda: NOW
    )


def typed(tmp_path, name, text):
    return write_run(tmp_path / name, ("c", [tool("type", text=text), tool("click")]))


def test_cli_classifies_a_baseline_run(tmp_path, monkeypatch, capsys):
    assert run_cli(tmp_path, monkeypatch, typed(tmp_path, "r1", "ok")) == 0
    assert json.loads(capsys.readouterr().out)["classification"] == "UNREACHED"
    assert run_cli(tmp_path, monkeypatch, typed(tmp_path, "r2", "한" * 200)) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["classification"] == "REACHED"
    assert out["inputs"][0]["scenario"] == "frontend/c#1"
    assert run_cli(tmp_path, monkeypatch, tmp_path / "none") == 1  # no logs
    assert json.loads(capsys.readouterr().out)["classification"] == "NO_INPUT"


@pytest.mark.parametrize(
    "bad",
    [{"extra": 1}, {"trim": "yes"}, {"compare": []}, {"request": {"method": "GET"}}],
)
def test_cli_rejects_a_bad_replay_spec(tmp_path, monkeypatch, bad):
    run = typed(tmp_path, "r", "a")
    assert run_cli(tmp_path, monkeypatch, run, {**SPEC, **bad}) == 2


def test_cli_refuses_an_unready_environment(tmp_path, monkeypatch, capsys):
    run = typed(tmp_path, "r", "a")
    assert run_cli(tmp_path, monkeypatch, run, ready="FAILED") == 2
    assert "environment not ready" in capsys.readouterr().out
