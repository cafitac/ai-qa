import json

import pytest
from test_core import descriptor, fixed_clock, main, scenarios

from aiqa.contracts import Config, EnvironmentDescriptor, validate
from aiqa.fakes import FakeAgentRunner, FileDescriptorSource, FileScenarioSource
from aiqa.storage import RunStorage
from aiqa.usecases import RunScenarios, descriptor_probe, exit_code

DOWN, UP = ("web",), ()


@pytest.fixture
def paths(tmp_path, monkeypatch):
    d, s = tmp_path / "descriptor.json", tmp_path / "scenarios.yaml"
    d.write_text(json.dumps(descriptor()))
    s.write_text(json.dumps(scenarios()))
    monkeypatch.setenv("AIQA_RUNS_DIR", str(tmp_path / "runs"))
    return d, s


def make(paths, statuses, probe):
    d, s = paths
    cfg = Config(runs_dir=d.parent / "runs")
    return RunScenarios(
        FileDescriptorSource(d),
        FileScenarioSource(s),
        FakeAgentRunner(statuses=statuses),
        cfg,
        agent_kind="fake",
        clock=fixed_clock,
        readiness_probe=probe,
    )


@pytest.mark.parametrize(
    "statuses,probes,expected",
    [
        ({}, [], 0),
        ({"web/test-1": "FAILED"}, [UP], 1),
        ({"web/test-1": "FAILED"}, [DOWN], 6),
        ({"web/test-0": "FAILED", "web/test-1": "FAILED"}, [UP, DOWN], 1),
        ({"web/test-0": "FAILED", "web/test-1": "FAILED"}, [DOWN, UP], 1),
        ({"web/test-0": "FAILED", "web/test-1": "FAILED"}, [DOWN, DOWN], 6),
    ],
)
def test_mixed_verdicts_same_exit_for_run_and_show(paths, statuses, probes, expected):
    uc = make(paths, statuses, lambda env: probes.pop(0))
    assert uc.execute("demo") == expected
    assert main(["show"]) == expected
    assert not probes


def test_exit_reducer_table():
    table = [
        ((), 0),
        (("PASSED", "SKIPPED"), 0),
        (("PASSED", "BLOCKED"), 6),
        (("BLOCKED", "FAILED", "PASSED"), 1),
    ]
    assert [exit_code(s) for s, _ in table] == [c for _, c in table]


def test_persisted_blocked_only_run_is_reloaded_by_show(paths, capsys):
    uc = make(paths, {"web/test-0": "FAILED", "web/test-1": "FAILED"}, lambda e: DOWN)
    assert uc.execute("demo") == 6
    run_id = uc.last_run.id
    capsys.readouterr()
    stored = RunStorage(paths[0].parent / "runs").load(run_id)
    assert stored["state"] == "COMPLETED"
    assert {r["status"] for r in stored["results"]} == {"BLOCKED"}
    assert {r["reason"] for r in stored["results"]} == {"environment"}
    assert main(["show", run_id]) == 6
    assert "BLOCKED — Readiness probe reports unhealthy: web" in capsys.readouterr().out


def test_agent_say_so_alone_is_not_blocked(paths):
    uc = make(paths, {"web/test-0": "BLOCKED", "web/test-1": "FAILED"}, lambda e: UP)
    assert uc.execute("demo") == 1
    assert {r.status for r in uc.last_run.results} == {"FAILED"}


def test_probe_error_or_missing_descriptor_keeps_failed(paths):
    d, _ = paths
    uc = make(paths, {"web/test-0": "FAILED"}, None)
    d.write_text(json.dumps({**descriptor(), "name": "other"}))
    assert uc.readiness_probe("demo") == UP
    d.write_text("{")
    assert uc.readiness_probe("demo") == UP


def test_descriptor_probe_flips_to_blocked_with_evidence(paths):
    calls = []

    class Flipping:
        def get(self, environment):
            calls.append(environment)
            data = descriptor()
            if len(calls) > 1:  # preflight read is healthy; the probe read is down
                data["services"][0]["health"] = "UNHEALTHY"
                data["readiness"]["allHealthy"] = False
            return EnvironmentDescriptor.parse(data)

    uc = make(paths, {"web/test-0": "FAILED"}, None)
    uc.descriptor_source = Flipping()
    uc.readiness_probe = descriptor_probe(uc.descriptor_source)
    assert uc.execute("demo") == 6
    blocked = uc.last_run.results[0]
    assert (blocked.status, blocked.reason) == ("BLOCKED", "environment")
    probe = uc.storage.root / uc.last_run.id / blocked.evidence[-1].uri
    assert json.loads(probe.read_text())["unhealthy"] == ["web"]


def test_report_projects_blocked_to_skipped(paths):
    uc = make(paths, {"web/test-0": "FAILED"}, lambda e: DOWN)
    assert uc.execute("demo") == 6
    path = uc.storage.root / uc.last_run.id
    payload = validate("qa-report", json.loads((path / "report.json").read_text()))
    first = payload["scenarios"][0]
    assert first["status"] == "SKIPPED"
    assert first["summary"].startswith("BLOCKED(environment): Readiness probe")
    assert payload["summary"] == {"passed": 1, "failed": 0, "skipped": 1}


def test_pre_blocked_stored_run_still_loads(paths):
    uc = make(paths, {"web/test-0": "FAILED"}, lambda e: UP)
    assert uc.execute("demo") == 1
    stored = RunStorage(paths[0].parent / "runs").load()
    assert {r["status"] for r in stored["results"]} <= {"PASSED", "FAILED", "SKIPPED"}
    assert main(["show"]) == 1
