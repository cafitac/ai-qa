"""Local assertions for live.sh; never echo untrusted report contents."""

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


def read(path):
    return json.loads(Path(path).read_text())


def check_run(mode, root, status=None):
    root = Path(root)
    run = read(root / "run.json")
    if mode == "B3":
        assert run["state"] == "REFUSED"
        assert run["refusal_reason"] == "environment_not_ready"
        assert not list(root.glob("scenarios/*/attempt-*"))
        assert not (root / "report.json").exists()
        return
    assert run["state"] == "COMPLETED"
    report = read(root / "report.json")
    schema = read("schemas/qa-report.schema.json")
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(report)
    results = {r["scenario_id"]: r for r in run["results"]}
    scenarios = {r["id"]: r for r in report["scenarios"]}
    assert set(results) == set(scenarios)
    assert all(
        scenarios[key]["status"] == value["status"] for key, value in results.items()
    )
    seed = "frontend/seed-notes-listed"
    add = "frontend/add-note-shows-first"
    if mode == "B5":
        assert set(results) == {seed}
        assert results[seed]["status"] == "FAILED"
        assert results[seed]["reason"] in ("turn_cap", "timeout")
        print("B5: COMPLETED reason=" + results[seed]["reason"])
        return
    assert set(results) == {seed, add}
    assert results[seed]["status"] == "PASSED"
    assert results[add]["status"] == ("PASSED" if mode == "B1" else "FAILED")
    if mode == "B1":
        commits = {s["service"]: s["commit_sha"] for s in read(status)["services"]}
        assert report["commits"] == commits
        for scenario in scenarios.values():
            assert any(
                e["type"] == "screenshot"
                and Path(e["uri"]).stem == "final"
                and (root / e["uri"]).is_file()
                for e in scenario["evidence"]
            )
    else:
        reason = results[add]["reason"]
        # Print only the gate enum, never agent-provided prose.
        reasons = read("schemas/scenario-result.schema.json")["properties"]["reason"][
            "enum"
        ]
        assert reason in reasons
        print("B2: add-note reason=" + (reason or "agent verdict"))


def main():
    mode, *args = sys.argv[1:]
    if mode == "ready":
        assert read(args[0])["state"] == "READY"
    elif mode == "empty":
        assert all(not value for value in read(args[0]).values())
    elif mode == "config":
        import yaml

        from aiqa.contracts import Config, duration

        config = Config.load()
        value = {
            "apiVersion": "ai-qa/v1",
            "hub": {
                "dashboard_url": config.dashboard_url,
                "access_team_domain": config.access_team_domain,
                "environment_domain": config.environment_domain,
            },
            "agent": {"kind": "claude", "model": config.agent_model},
            "budget": {
                "max_scenarios": min(config.max_scenarios, 2),
                "max_turns": min(config.max_turns, 25),
                "scenario_timeout": (
                    config.scenario_timeout
                    if duration(config.scenario_timeout) <= 300
                    else "300s"
                ),
                "protocol_retries": min(config.protocol_retries, 1),
            },
            "runs_dir": str(config.runs_dir),
            "playwright_mcp": config.playwright_mcp,
        }
        Path(args[0]).write_text(yaml.safe_dump(value))
        value["budget"]["max_turns"] = 1
        Path(args[1]).write_text(yaml.safe_dump(value))
    elif mode in ("reservation", "runs-dir"):
        from aiqa.contracts import Config

        config = Config.load(Path(args[0]))
        if mode == "runs-dir":
            print(config.runs_dir)
        else:
            scenarios = 1 if len(args) > 1 else config.max_scenarios
            print(scenarios + config.protocol_retries)
    else:
        check_run(mode, *args)


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 - suppress untrusted validation payloads
        print(
            "Live assertion failed (details suppressed to protect secrets)",
            file=sys.stderr,
        )
        sys.exit(1)
