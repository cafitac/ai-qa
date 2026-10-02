"""Offline checks of the live evidence assertions; no CLI or network calls."""

import json
import runpy
from pathlib import Path

import pytest

CHECK = runpy.run_path(str(Path(__file__).parents[1] / "e2e/check.py"))["check_run"]


def write(path, value):
    path.write_text(json.dumps(value))


def test_refusal_requires_zero_attempts(tmp_path):
    write(
        tmp_path / "run.json",
        {"state": "REFUSED", "refusal_reason": "environment_not_ready"},
    )
    CHECK("B3", tmp_path)
    (tmp_path / "scenarios/frontend__seed-notes-listed/attempt-1").mkdir(parents=True)
    with pytest.raises(AssertionError):
        CHECK("B3", tmp_path)


@pytest.mark.parametrize("failure", ["commit", "screenshot", "verdict"])
def test_success_assertions_reject_bad_evidence(tmp_path, failure):
    ids = ["frontend/seed-notes-listed", "frontend/add-note-shows-first"]
    write(
        tmp_path / "run.json",
        {
            "state": "COMPLETED",
            "results": [{"scenario_id": key, "status": "PASSED"} for key in ids],
        },
    )
    screenshot = tmp_path / "final.png"
    screenshot.write_bytes(b"synthetic image")
    report = {
        "apiVersion": "preview-hub/v1",
        "kind": "QaReport",
        "environment": "qa-ok-test",
        "commits": {"frontend": "a" * 40},
        "startedAt": "2026-10-01T00:00:00Z",
        "finishedAt": "2026-10-01T00:01:00Z",
        "scenarios": [
            {
                "id": key,
                "status": "PASSED",
                "summary": "synthetic",
                "evidence": [{"type": "screenshot", "uri": "final.png"}],
            }
            for key in ids
        ],
        "summary": {"passed": 2, "failed": 0, "skipped": 0},
    }
    status = tmp_path / "status.json"
    write(status, {"services": [{"service": "frontend", "commit_sha": "a" * 40}]})
    write(tmp_path / "report.json", report)
    CHECK("B1", tmp_path, status)
    if failure == "commit":
        report["commits"]["frontend"] = "b" * 40
    elif failure == "screenshot":
        screenshot.unlink()
    else:
        report["scenarios"][0]["status"] = "FAILED"
    write(tmp_path / "report.json", report)
    with pytest.raises(AssertionError):
        CHECK("B1", tmp_path, status)


@pytest.mark.parametrize(
    "scenarios,turns,timeout,retries,expected_budget",
    [
        (7, 9, "42s", 0, (2, 25, "300s", 1)),
        (1, 50, "6m", 1, (2, 25, "300s", 1)),
        (2, 25, "5m", 1, (2, 25, "300s", 1)),
    ],
)
def test_generated_configs_preserve_environment_and_pin_budget(
    tmp_path, monkeypatch, capsys, scenarios, turns, timeout, retries, expected_budget
):
    import yaml

    from aiqa.contracts import Config

    source = {
        "apiVersion": "ai-qa/v1",
        "hub": {
            "dashboard_url": "https://dashboard.example",
            "access_team_domain": "team.cloudflareaccess.com",
            "environment_domain": "preview.example",
        },
        "agent": {"kind": "codex", "model": "synthetic-model"},
        "budget": {
            "max_scenarios": scenarios,
            "max_turns": turns,
            "scenario_timeout": timeout,
            "protocol_retries": retries,
        },
        "runs_dir": "synthetic-runs",
        "playwright_mcp": "@playwright/mcp@0.0.83",
    }
    source_path = tmp_path / "source.yaml"
    source_path.write_text(yaml.safe_dump(source))
    monkeypatch.setenv("AIQA_CONFIG", str(source_path))
    monkeypatch.delenv("AIQA_RUNS_DIR", raising=False)
    monkeypatch.delenv("AIQA_STATE_FILE", raising=False)
    normal, capped = tmp_path / "normal.yaml", tmp_path / "capped.yaml"
    monkeypatch.setattr("sys.argv", ["check.py", "config", str(normal), str(capped)])
    runpy.run_path(str(Path(__file__).parents[1] / "e2e/check.py"))["main"]()
    expected = {
        **source,
        "agent": {**source["agent"], "kind": "claude"},
        "budget": dict(
            zip(
                ("max_scenarios", "max_turns", "scenario_timeout", "protocol_retries"),
                expected_budget,
                strict=True,
            )
        ),
    }
    assert yaml.safe_load(normal.read_text()) == expected
    expected_capped = {**expected, "budget": {**expected["budget"], "max_turns": 1}}
    assert yaml.safe_load(capped.read_text()) == expected_capped
    assert Config.load(normal).agent_kind == "claude"
    assert Config.load(capped).environment_domain == "preview.example"
    assert Config.load(capped).agent_model == "synthetic-model"
    main = runpy.run_path(str(Path(__file__).parents[1] / "e2e/check.py"))["main"]
    for config, extra, reservation in (
        (normal, [], expected_budget[0] + expected_budget[3]),
        (capped, ["--only", "frontend/seed-notes-listed"], 1 + expected_budget[3]),
    ):
        monkeypatch.setattr(
            "sys.argv", ["check.py", "reservation", str(config), *extra]
        )
        main()
        assert capsys.readouterr().out.strip() == str(reservation)
    monkeypatch.setattr("sys.argv", ["check.py", "runs-dir", str(normal)])
    main()
    assert capsys.readouterr().out.strip() == "synthetic-runs"


def test_live_run_pins_claude_and_reserves_before_invocation():
    script = (Path(__file__).parents[1] / "e2e/live.sh").read_text()
    run = script.split("run() {", 1)[1].split("\nready()", 1)[0]
    assert '--config "$config" --agent claude "$@"' in run
    assert run.index('reserve "$(check reservation') < run.index("uv run aiqa run")
    assert "export AIQA_RUNS_DIR=" not in script
