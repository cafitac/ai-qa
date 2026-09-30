import hashlib
import json
import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from aiqa.cli import main as cli_main
from aiqa.contracts import (
    Config,
    EnvironmentDescriptor,
    InvalidInput,
    duration,
    load_yaml,
    parse_scenarios,
    validate,
)
from aiqa.fakes import FakeAgentRunner, FileDescriptorSource, FileScenarioSource
from aiqa.ports import AgentOutput
from aiqa.run import Budget, Run, ScenarioResult
from aiqa.storage import RunStorage, atomic_write
from aiqa.usecases import Refused, RunScenarios

FIXED_TIME = datetime(2040, 1, 15, tzinfo=UTC)


def fixed_clock():
    return FIXED_TIME


def main(argv, *, clock=fixed_clock):
    return cli_main(argv, clock=clock)


def descriptor(at=FIXED_TIME):
    return {
        "apiVersion": "preview-hub/v1",
        "kind": "EnvironmentDescriptor",
        "name": "demo",
        "state": "READY",
        "createdAt": (at - timedelta(days=1)).isoformat(),
        "expiresAt": (at + timedelta(days=1)).isoformat(),
        "entryUrl": "https://demo.example/",
        "proxy": {"hostPort": 8080, "inNetworkAddress": "proxy:80"},
        "services": [
            {
                "name": "web",
                "repo": "cafitac/web",
                "ref": "main",
                "commit": "a" * 40,
                "publicUrl": "https://demo.example/",
                "health": "HEALTHY",
            }
        ],
        "testAccounts": [],
        "readiness": {"allHealthy": True, "checkedAt": at.isoformat()},
    }


def scenarios(count=2):
    return {
        "apiVersion": "ai-qa/v1",
        "scenarios": [
            {
                "id": f"test-{i}",
                "title": "Test",
                "steps": ["Click"],
                "expect": ["Visible"],
                "tags": ["smoke"],
            }
            for i in range(count)
        ],
    }


@pytest.fixture
def setup_run(tmp_path):
    d, s = tmp_path / "descriptor.json", tmp_path / "scenarios.yaml"
    d.write_text(json.dumps(descriptor()))
    s.write_text(json.dumps(scenarios()))
    cfg = Config(runs_dir=tmp_path / "runs")
    return d, s, cfg


def usecase(setup_run, outputs=(), **kw):
    d, s, cfg = setup_run
    fake = FakeAgentRunner(outputs)
    uc = RunScenarios(
        FileDescriptorSource(d),
        FileScenarioSource(s),
        fake,
        kw.pop("config", cfg),
        agent_kind="fake",
        clock=kw.pop("clock", fixed_clock),
        **kw,
    )
    return uc, fake


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(extra=True),
        lambda d: d["scenarios"][0].update(id="A"),
        lambda d: d["scenarios"][0].update(id="abc\n"),
        lambda d: d["scenarios"][0].update(steps=["x"] * 21),
        lambda d: d["scenarios"][0].update(expect=["x"] * 11),
        lambda d: d["scenarios"][0].update(title="x" * 501),
        lambda d: d["scenarios"][0].update(timeout="301s"),
        lambda d: d["scenarios"].append(d["scenarios"][0]),
        lambda d: d.update(scenarios=scenarios(51)["scenarios"]),
    ],
)
def test_scenario_limits(mutate):
    value = scenarios()
    mutate(value)
    with pytest.raises(InvalidInput):
        parse_scenarios(value, "web")


def test_parsers(tmp_path):
    assert len(parse_scenarios(scenarios(50), "web")) == 50
    assert duration("5m") == 300
    for bad in ("0s", "-1s", "1.5s", "1", "9999999999999999d"):
        with pytest.raises(InvalidInput):
            duration(bad)
    cfg = Config.parse(
        {"apiVersion": "ai-qa/v1"},
        {"AIQA_RUNS_DIR": str(tmp_path), "AIQA_STATE_FILE": "/tmp/synthetic-state"},
    )
    assert cfg.max_turns == 25 and cfg.runs_dir == tmp_path
    file = tmp_path / "config.yaml"
    file.write_text("apiVersion: ai-qa/v1\nbudget:\n  max_turns: 2\n")
    assert Config.load(environ={"AIQA_CONFIG": str(file)}).max_turns == 2
    with pytest.raises(InvalidInput):
        Config.parse({"apiVersion": "ai-qa/v1", "budget": {"protocol_retries": 2}}, {})
    d = EnvironmentDescriptor.parse(descriptor())
    assert d.is_ready(FIXED_TIME) and d.commits() == {"web": "a" * 40}
    assert d.origins() == ("https://demo.example",)


def test_state_machine():
    run = Run("demo-20260930T000000Z", "demo", Budget(), "fake", clock=fixed_clock)
    result = ScenarioResult("web/test-0", "PASSED", "ok")
    with pytest.raises(ValueError):
        run.record(result)
    with pytest.raises(ValueError):
        run.transition("COMPLETED")
    run.transition("PREFLIGHT")
    commits = {"web": "a" * 40}
    run.start(commits, ["web/test-0"])
    commits["web"] = "b" * 40
    assert run.commits["web"] == "a" * 40
    with pytest.raises(TypeError):
        run.commits["web"] = "b" * 40
    with pytest.raises(ValueError):
        run.transition("COMPLETED")
    run.record(result)
    with pytest.raises(ValueError):
        run.record(result)
    run.transition("COMPLETED")
    with pytest.raises(ValueError):
        run.transition("RUNNING")
    with pytest.raises(ValueError):
        run.record(result)


@pytest.mark.parametrize("failure", [False, True])
def test_full_run(setup_run, failure):
    uc, fake = usecase(setup_run)
    if failure:
        fake.statuses = {"web/test-0": "FAILED"}
    assert uc.execute("demo") == int(failure)
    run = uc.last_run
    assert run.state == "COMPLETED" and len(fake.calls) == 2
    path = setup_run[2].runs_dir / run.id
    validate("qa-report", json.loads((path / "report.json").read_text()))
    validate("run", json.loads((path / "run.json").read_text()))
    assert (path / "summary.md").exists()
    assert run.results[0].evidence[0].uri.startswith("scenarios/web__test-0/")


@pytest.mark.parametrize(
    "case,code",
    [
        ("unknown", 3),
        ("state", 3),
        ("health", 3),
        ("service_health", 3),
        ("empty", 3),
        ("invalid", 2),
    ],
)
def test_refusals(setup_run, case, code):
    d, s, cfg = setup_run
    value = descriptor()
    if case == "unknown":
        value["name"] = "other"
    if case == "state":
        value["state"] = "BUILDING"
    if case == "health":
        value["readiness"]["allHealthy"] = False
    if case == "service_health":
        value["services"][0]["health"] = "UNKNOWN"
    d.write_text(json.dumps(value))
    if case == "empty":
        s.write_text(json.dumps(scenarios(0)))
    if case == "invalid":
        s.write_text("invalid: [")
    uc, fake = usecase(setup_run)
    assert uc.execute("demo") == code
    assert not fake.calls and uc.last_run.state == "REFUSED"
    assert not (cfg.runs_dir / uc.last_run.id / "report.json").exists()


def test_budget_skips(setup_run):
    uc, fake = usecase(setup_run, config=replace(setup_run[2], max_scenarios=1))
    assert uc.execute("demo") == 0
    assert len(fake.calls) == 1 and uc.last_run.results[1].status == "SKIPPED"
    assert fake.calls[0][1].max_turns == 25 and fake.calls[0][1].timeout_seconds == 300


@pytest.mark.parametrize(
    "output,reason",
    [
        (AgentOutput('{"status":"PASSED"}', turns=26), "turn_cap"),
        (AgentOutput('{"status":"PASSED"}', seconds=301), "timeout"),
        (AgentOutput('{"status":"PASSED"}', exit_code=1), "agent_error"),
    ],
)
def test_caps_continue(setup_run, output, reason):
    uc, fake = usecase(setup_run, [output])
    assert uc.execute("demo") == 1
    assert len(fake.calls) == 2
    assert (
        uc.last_run.results[0].reason == reason
        and uc.last_run.results[1].status == "PASSED"
    )


def test_protocol_retry_is_global(setup_run):
    uc, fake = usecase(
        setup_run, [AgentOutput("bad"), AgentOutput("bad"), AgentOutput("bad")]
    )
    assert uc.execute("demo") == 1 and len(fake.calls) == 3
    assert all(r.reason == "agent_protocol" for r in uc.last_run.results)


def test_protocol_retry_pass(setup_run):
    uc, fake = usecase(setup_run, [AgentOutput("bad")])
    assert uc.execute("demo") == 0 and len(fake.calls) == 3


@pytest.mark.parametrize(
    "error", [KeyboardInterrupt(), RuntimeError("synthetic"), Refused("login_required")]
)
def test_abort_partial(setup_run, error):
    class Runner(FakeAgentRunner):
        def run(self, scenario, context):
            if self.calls:
                raise error
            return super().run(scenario, context)

    uc, _ = usecase(setup_run)
    uc.agent_runner = Runner()
    assert uc.execute("demo") == 4
    assert uc.last_run.state == "ABORTED" and len(uc.last_run.results) == 1
    assert not (setup_run[2].runs_dir / uc.last_run.id / "report.json").exists()


def test_session_refusal(setup_run):
    class Session:
        def preflight(self, url):
            raise Refused("login_required")

    uc, fake = usecase(setup_run, browser_session=Session())
    assert uc.execute("demo") == 3 and not fake.calls


def test_atomic_collision_interrupted(tmp_path, monkeypatch):
    path = tmp_path / "data.json"
    atomic_write(path, "old")

    def fail(*args):
        raise OSError("synthetic")

    with monkeypatch.context() as patch:
        patch.setattr("aiqa.storage.os.replace", fail)
        with pytest.raises(OSError):
            atomic_write(path, "new")
    assert path.read_text() == "old" and list(tmp_path.iterdir()) == [path]
    storage = RunStorage(tmp_path / "runs")
    at = datetime(2026, 9, 30, tzinfo=UTC)
    folder = storage.create("demo", at)
    with pytest.raises(InvalidInput):
        storage.create("demo", at)
    run = Run(folder.name, "demo", Budget(), "fake", clock=fixed_clock)
    run.transition("PREFLIGHT")
    run.start({"web": "a" * 40}, ["web/test-0"])
    storage.save(run)
    monkeypatch.setattr("aiqa.storage.pid_alive", lambda pid: False)
    assert storage.load()["state"] == "INTERRUPTED"
    assert json.loads((folder / "run.json").read_text())["state"] == "RUNNING"


def test_cli(setup_run, monkeypatch, capsys):
    d, s, cfg = setup_run
    monkeypatch.setenv("AIQA_RUNS_DIR", str(cfg.runs_dir))
    assert main(["run", "demo", "--agent", "claude"]) == 2
    assert "not available yet" in capsys.readouterr().out
    assert main(["run", "demo", "--agent", "codex"]) == 2
    assert main(["run", "demo", "--agent", "fake"]) == 2
    assert main(["show"]) == 2
    assert (
        main(
            [
                "run",
                "demo",
                "--agent",
                "fake",
                "--descriptor",
                str(d),
                "--scenarios",
                str(s),
            ]
        )
        == 0
    )
    assert main(["show"]) == 0


def test_vendor_hashes():
    root = Path(__file__).parent.parent / "schemas"
    document = (root / "VENDORED.md").read_text()
    assert "8eed84712e6a4b76a183e1c8cdbffa009a65d0aa" in document
    hashes = dict(
        re.findall(r"`([^`]+\.schema\.json)` SHA-256: `([0-9a-f]{64})`", document)
    )
    assert set(hashes) == {
        "environment-descriptor.schema.json",
        "qa-report.schema.json",
    }
    for name, expected in hashes.items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected


def test_filters_and_timeout(setup_run):
    _d, s, _cfg = setup_run
    data = scenarios()
    data["scenarios"][0]["timeout"] = "5s"
    s.write_text(json.dumps(data))
    uc, fake = usecase(setup_run)
    assert uc.execute("demo", tags=("smoke",), only=("web/test-0",)) == 0
    assert len(fake.calls) == 1 and fake.calls[0][1].timeout_seconds == 5


@pytest.mark.parametrize(
    "case,expected", [("unknown", 3), ("invalid", 2), ("interrupted", 4), ("failed", 1)]
)
def test_cli_codes(setup_run, monkeypatch, case, expected):
    d, s, cfg = setup_run
    monkeypatch.setenv("AIQA_RUNS_DIR", str(cfg.runs_dir))
    args = [
        "run",
        "demo",
        "--agent",
        "fake",
        "--descriptor",
        str(d),
        "--scenarios",
        str(s),
    ]
    if case == "unknown":
        data = descriptor()
        data["name"] = "other"
        d.write_text(json.dumps(data))
    if case == "invalid":
        s.write_text("bad: [")
    if case == "failed":
        monkeypatch.setattr(
            "aiqa.cli.FakeAgentRunner",
            lambda: FakeAgentRunner(statuses={"web/test-0": "FAILED"}),
        )
    if case == "interrupted":
        uc, _ = usecase(setup_run)
        assert uc.execute("demo") == 0
        file = cfg.runs_dir / uc.last_run.id / "run.json"
        data = json.loads(file.read_text())
        data["state"] = "RUNNING"
        file.write_text(json.dumps(data))
        monkeypatch.setattr("aiqa.storage.pid_alive", lambda pid: False)
        args = ["show"]
    assert main(args) == expected


def test_multi_service_file_refused(setup_run):
    d, _s, _cfg = setup_run
    data = descriptor()
    data["services"].append({**data["services"][0], "name": "api"})
    d.write_text(json.dumps(data))
    uc, fake = usecase(setup_run)
    assert uc.execute("demo") == 2 and not fake.calls


def test_transition_terminal_states():
    for terminal in ("REFUSED", "ABORTED"):
        run = Run("demo-20260930T000000Z", "demo", Budget(), "fake", clock=fixed_clock)
        run.transition("PREFLIGHT")
        run.transition(terminal)
        assert run.finished_at
        for next_state in (
            "CREATED",
            "PREFLIGHT",
            "RUNNING",
            "COMPLETED",
            "REFUSED",
            "ABORTED",
        ):
            with pytest.raises(ValueError):
                run.transition(next_state)


def test_report_validation_error_aborts(setup_run, monkeypatch):
    uc, fake = usecase(setup_run)

    def invalid_report(run):
        raise InvalidInput("synthetic report failure")

    monkeypatch.setattr("aiqa.usecases.report", invalid_report)
    assert uc.execute("demo") == 4
    assert uc.last_run.state == "ABORTED" and len(fake.calls) == 2
    assert len(uc.last_run.results) == 2
    assert not (setup_run[2].runs_dir / uc.last_run.id / "report.json").exists()


def test_gate_receives_adapter_inputs(setup_run):
    from aiqa.usecases import JsonVerdictGate

    class Gate(JsonVerdictGate):
        def accept(self, scenario, output, transcript, files, caps):
            assert transcript in files
            assert caps.allowed_origins == (
                "https://cafitac.cloudflareaccess.com",
                "https://demo.example",
            )
            return super().accept(scenario, output, transcript, files, caps)

    uc, _fake = usecase(setup_run, verdict_gate=Gate())
    assert uc.execute("demo") == 0


@pytest.mark.parametrize(
    "start",
    [
        "/\t/evil.example/x",
        "/\r/x",
        "/\n/x",
        "/x\n",
        "/ x",
        "/\\evil",
        "/\x00x",
        "/\x7fx",
        "/\u00a0x",
    ],
)
def test_unsafe_start_rejected(start):
    data = scenarios(1)
    data["scenarios"][0]["start"] = start
    with pytest.raises(InvalidInput):
        parse_scenarios(data, "web")


def test_joined_start_origin_guard(setup_run):
    class Source:
        def load(self, *args):
            return [
                replace(
                    parse_scenarios(scenarios(1), "web")[0], start="/\t/evil.example/x"
                )
            ]

    uc, fake = usecase(setup_run)
    uc.scenario_source = Source()
    assert uc.execute("demo") == 2
    assert uc.last_run.refusal_reason == "invalid_scenarios"
    assert not fake.calls


def test_latest_across_environments(tmp_path, monkeypatch, capsys):
    storage = RunStorage(tmp_path)
    for env, day in (("zulu", 29), ("alpha", 30)):
        folder = storage.create(env, datetime(2026, 9, day, tzinfo=UTC))
        storage.save(Run(folder.name, env, Budget(), "fake", clock=fixed_clock))
    foreign = tmp_path / "zzzz-foreign"
    foreign.mkdir()
    (foreign / "run.json").write_text("{}")
    assert storage.list() == ["alpha-20260930T000000Z", "zulu-20260929T000000Z"]
    monkeypatch.setenv("AIQA_RUNS_DIR", str(tmp_path))
    assert main(["show"]) == 5
    assert "alpha-20260930T000000Z" in capsys.readouterr().out


@pytest.mark.parametrize("state", ["CREATED", "PREFLIGHT", "RUNNING"])
def test_dead_pid_active_states(tmp_path, monkeypatch, state):
    storage = RunStorage(tmp_path)
    folder = storage.create("demo", fixed_clock())
    run = Run(folder.name, "demo", Budget(), "fake", clock=fixed_clock)
    if state != "CREATED":
        run.transition("PREFLIGHT")
    if state == "RUNNING":
        run.start({"web": "a" * 40}, ["web/test-0"])
    storage.save(run)
    monkeypatch.setattr("aiqa.storage.pid_alive", lambda pid: False)
    monkeypatch.setenv("AIQA_RUNS_DIR", str(tmp_path))
    assert storage.load()["state"] == "INTERRUPTED"
    assert main(["show"]) == 4
    assert json.loads((folder / "run.json").read_text())["state"] == state


@pytest.mark.parametrize("case", ["missing", "schema", "url", "encoding"])
def test_invalid_descriptor_reason(setup_run, case):
    d, _, cfg = setup_run
    if case == "missing":
        d.unlink()
    elif case == "schema":
        d.write_text("{}")
    elif case == "encoding":
        d.write_bytes(b"\xff")
    else:
        data = descriptor()
        data["entryUrl"] = "https://:secret@demo.example/"
        d.write_text(json.dumps(data))
    uc, fake = usecase(setup_run)
    assert uc.execute("demo") == 2
    assert uc.last_run.refusal_reason == "invalid_descriptor"
    saved = RunStorage(cfg.runs_dir).load()
    assert saved["refusal_reason"] == "invalid_descriptor"
    assert not fake.calls


@pytest.mark.parametrize("kind", ["config", "scenario", "run"])
def test_non_utf8_inputs(setup_run, monkeypatch, kind):
    _, s, cfg = setup_run
    monkeypatch.setenv("AIQA_RUNS_DIR", str(cfg.runs_dir))
    if kind == "config":
        config = s.parent / "bad.yaml"
        config.write_bytes(b"\xff")
        assert main(["show", "--config", str(config)]) == 2
    elif kind == "scenario":
        s.write_bytes(b"\xff")
        uc, _ = usecase(setup_run)
        assert uc.execute("demo") == 2
        assert uc.last_run.refusal_reason == "invalid_scenarios"
    else:
        folder = RunStorage(cfg.runs_dir).create("demo")
        (folder / "run.json").write_bytes(b"\xff")
        assert main(["show"]) == 2


@pytest.mark.parametrize("retries", [0, 1])
def test_enforced_agent_call_cap(setup_run, retries):
    cfg = replace(setup_run[2], max_scenarios=1, protocol_retries=retries)
    uc, fake = usecase(setup_run, [AgentOutput("bad")] * 3, config=cfg)
    assert uc.execute("demo") == 1
    assert len(fake.calls) == Budget(1, protocol_retries=retries).max_agent_calls
    assert uc.last_run.results[1].status == "SKIPPED"


def test_ci_uses_locked_sync():
    workflow = Path(__file__).parent.parent / ".github/workflows/ci.yml"
    assert "- run: uv sync --locked\n" in workflow.read_text()


def test_report_only_after_durable_completion(setup_run, monkeypatch, capsys):
    uc, _ = usecase(setup_run)
    save = uc.storage.save

    def checked_save(run):
        assert not (setup_run[2].runs_dir / run.id / "report.json").exists()
        if run.state == "COMPLETED":
            raise OSError("synthetic final save failure")
        save(run)

    monkeypatch.setattr(uc.storage, "save", checked_save)
    assert run_cli(setup_run, monkeypatch, uc) == 4
    output = capsys.readouterr().out
    assert f"{uc.last_run.id}: ABORTED" in output
    assert RunStorage(setup_run[2].runs_dir).load()["state"] == "ABORTED"
    assert not (setup_run[2].runs_dir / uc.last_run.id / "report.json").exists()


@pytest.mark.parametrize(
    "url",
    [
        "https://:secret@host/",
        "https://user@host/",
        "https://@host/",
        "https://host:bad/",
    ],
)
def test_origin_rejects_userinfo_and_invalid_ports(url):
    data = descriptor()
    data["entryUrl"] = url
    with pytest.raises(InvalidInput):
        EnvironmentDescriptor.parse(data).origins()


def test_origin_rebuilt_from_hostname():
    data = descriptor()
    data["entryUrl"] = "https://DEMO.example:8443/path"
    assert EnvironmentDescriptor.parse(data).origins() == (
        "https://demo.example",
        "https://demo.example:8443",
    )


@pytest.mark.parametrize("failure", ["report.json", "summary.md"])
def test_completion_artifact_failure_recovers(setup_run, monkeypatch, failure, capsys):
    import aiqa.usecases as module

    uc, _ = usecase(setup_run)
    original = module.write_json if failure == "report.json" else module.atomic_write
    failed = False

    def fail_once(path, value):
        nonlocal failed
        if path.name == failure and not failed:
            failed = True
            assert (
                json.loads((path.parent / "run.json").read_text())["state"]
                == "COMPLETED"
            )
            raise OSError("synthetic artifact failure")
        original(path, value)

    monkeypatch.setattr(
        module, "write_json" if failure == "report.json" else "atomic_write", fail_once
    )
    assert run_cli(setup_run, monkeypatch, uc) == 4
    output = capsys.readouterr().out
    assert f"{uc.last_run.id}: ABORTED" in output
    folder = setup_run[2].runs_dir / uc.last_run.id
    assert json.loads((folder / "run.json").read_text())["state"] == "ABORTED"
    assert not (folder / "report.json").exists()
    assert "State: ABORTED" in (folder / "summary.md").read_text()


def test_invalid_runs_directory(setup_run, monkeypatch, capsys):
    d, s, cfg = setup_run
    cfg.runs_dir.write_text("regular file")
    uc, _ = usecase(setup_run)
    assert uc.execute("demo") == 4
    monkeypatch.setenv("AIQA_RUNS_DIR", str(cfg.runs_dir))
    assert (
        main(
            [
                "run",
                "demo",
                "--descriptor",
                str(d),
                "--scenarios",
                str(s),
                "--agent",
                "fake",
            ]
        )
        == 4
    )
    assert "storage error" in capsys.readouterr().out.lower()


@pytest.mark.parametrize("phase", ["CREATED", "PREFLIGHT", "REFUSED"])
def test_storage_save_errors_are_infrastructure(setup_run, monkeypatch, phase, capsys):
    uc, _ = usecase(setup_run)
    if phase == "REFUSED":
        setup_run[0].unlink()
    original = uc.storage.save

    def fail_save(run):
        if run.state == phase:
            raise OSError("synthetic save failure")
        original(run)

    monkeypatch.setattr(uc.storage, "save", fail_save)
    assert run_cli(setup_run, monkeypatch, uc) == 4
    if phase != "CREATED":
        assert f"{uc.last_run.id}: ABORTED" in capsys.readouterr().out


def test_directory_scenarios_use_entry_origin(setup_run):
    d, s, cfg = setup_run
    value = descriptor()
    value["services"].append(
        {
            **value["services"][0],
            "name": "api",
            "repo": "cafitac/api",
            "publicUrl": "https://api.example/",
        }
    )
    d.write_text(json.dumps(value))
    directory = s.parent / "services"
    directory.mkdir()
    for service in ("web", "api"):
        data = scenarios(1)
        data["scenarios"][0]["start"] = f"/{service}"
        (directory / f"{service}.yaml").write_text(json.dumps(data))
    uc, fake = usecase((d, directory, cfg))
    assert uc.execute("demo") == 0
    assert [
        (scenario.qualified_id, context.start_url) for scenario, context in fake.calls
    ] == [
        ("web/test-0", "https://demo.example/web"),
        ("api/test-0", "https://demo.example/api"),
    ]


def test_atomic_write_utf8_bytes(tmp_path):
    path = tmp_path / "unicode.txt"
    atomic_write(path, "메모 café\n")
    assert path.read_bytes() == "메모 café\n".encode()


@pytest.mark.parametrize(
    "state,reason,status,code",
    [
        ("COMPLETED", None, "PASSED", 0),
        ("COMPLETED", None, "FAILED", 1),
        ("REFUSED", "no_scenarios", None, 3),
        ("REFUSED", "invalid_descriptor", None, 2),
        ("REFUSED", "invalid_scenarios", None, 2),
        ("ABORTED", None, None, 4),
    ],
)
def test_show_represents_run_exit_code(
    tmp_path, monkeypatch, state, reason, status, code
):
    storage = RunStorage(tmp_path)
    folder = storage.create("demo", fixed_clock())
    run = Run(folder.name, "demo", Budget(), "fake", clock=fixed_clock)
    run.transition("PREFLIGHT")
    if state == "COMPLETED":
        run.start({"web": "a" * 40}, ["web/test-0"])
        run.record(ScenarioResult("web/test-0", status, "synthetic"))
    run.refusal_reason = reason
    run.transition(state)
    storage.save(run)
    if state == "COMPLETED":
        from aiqa.usecases import report

        (folder / "report.json").write_text(json.dumps(report(run)))
    monkeypatch.setenv("AIQA_RUNS_DIR", str(tmp_path))
    assert main(["show"]) == code


@pytest.mark.parametrize("completed_saved", [False, True])
def test_failed_abort_save_uses_actual_disk_state(
    setup_run, monkeypatch, completed_saved
):
    import aiqa.usecases as module

    uc, _ = usecase(setup_run)
    original_save = uc.storage.save
    original_write = module.write_json

    def fail_completion(run):
        if run.state == "COMPLETED" and not completed_saved:
            raise OSError("synthetic completion failure")
        original_save(run)

    def fail_recovery(path, value):
        if path.name == "report.json" or (
            path.name == "run.json" and value["state"] == "ABORTED"
        ):
            raise OSError("synthetic recovery failure")
        original_write(path, value)

    monkeypatch.setattr(uc.storage, "save", fail_completion)
    monkeypatch.setattr(module, "write_json", fail_recovery)
    assert uc.execute("demo") == 4
    folder = setup_run[2].runs_dir / uc.last_run.id
    saved = json.loads((folder / "run.json").read_text())
    assert saved["state"] == ("COMPLETED" if completed_saved else "RUNNING")
    assert not (folder / "report.json").exists()
    if completed_saved:
        assert "State: INTERRUPTED" in (folder / "summary.md").read_text()
        assert uc.persisted_run["state"] == "INTERRUPTED"
        monkeypatch.setenv("AIQA_RUNS_DIR", str(setup_run[2].runs_dir))
        assert main(["show"]) == 4
    else:
        assert "State: RUNNING" in (folder / "summary.md").read_text()


def run_cli(setup_run, monkeypatch, uc):
    d, s, cfg = setup_run
    monkeypatch.setenv("AIQA_RUNS_DIR", str(cfg.runs_dir))
    monkeypatch.setattr("aiqa.cli.RunScenarios", lambda *a, **kw: uc)
    return main(
        [
            "run",
            "demo",
            "--descriptor",
            str(d),
            "--scenarios",
            str(s),
            "--agent",
            "fake",
        ]
    )


def test_tab_indented_json_descriptor(setup_run):
    d, _, _ = setup_run
    d.write_text(json.dumps(descriptor(), indent="\t"))
    assert FileDescriptorSource(d).get("demo").is_ready(FIXED_TIME)


@pytest.mark.parametrize("content", ["{broken", "name: demo", "\xff"])
def test_invalid_json_descriptor(tmp_path, content):
    path = tmp_path / "descriptor.json"
    path.write_bytes(content.encode("latin-1"))
    with pytest.raises(InvalidInput):
        FileDescriptorSource(path).get("demo")


@pytest.mark.parametrize("field", ["name", "service", "commit"])
def test_descriptor_patterns_reject_final_newline(field):
    data = descriptor()
    target = data if field == "name" else data["services"][0]
    key = "name" if field == "service" else field
    target[key] += "\n"
    with pytest.raises(InvalidInput):
        EnvironmentDescriptor.parse(data)


@pytest.mark.parametrize("kind", ["run", "scenario-result"])
def test_run_identity_patterns_reject_final_newline(kind):
    result = ScenarioResult("web/test-0", "PASSED", "ok").as_dict()
    run = Run(
        "demo-20260930T000000Z", "demo", Budget(), "fake", clock=fixed_clock
    ).as_dict()
    data = run if kind == "run" else result
    key = "id" if kind == "run" else "scenario_id"
    data[key] += "\n"
    with pytest.raises(InvalidInput):
        validate(kind, data)


@pytest.mark.parametrize("pid", [2**100, 1.5, 1.0, True, -1, 0])
def test_corrupt_pid(setup_run, monkeypatch, pid):
    from aiqa.storage import pid_alive

    assert not pid_alive(pid)
    uc, _ = usecase(setup_run)
    assert uc.execute("demo") == 0
    path = setup_run[2].runs_dir / uc.last_run.id / "run.json"
    data = json.loads(path.read_text())
    data.update(state="RUNNING", pid=pid)
    path.write_text(json.dumps(data))
    monkeypatch.setenv("AIQA_RUNS_DIR", str(setup_run[2].runs_dir))
    assert main(["show"]) == 2


@pytest.mark.parametrize(
    "error", [OverflowError, TypeError, ValueError, ProcessLookupError]
)
def test_unsendable_pid(monkeypatch, error):
    from aiqa.storage import pid_alive

    def kill(*args):
        raise error()

    monkeypatch.setattr("aiqa.storage.os.kill", kill)
    assert not pid_alive(123)


@pytest.mark.parametrize(
    "error,reason", [(RuntimeError, "RuntimeError"), (KeyboardInterrupt, "interrupted")]
)
def test_abort_reason(setup_run, monkeypatch, capsys, error, reason):
    uc, _ = usecase(setup_run)

    def fail(*args):
        raise error("private message")

    monkeypatch.setattr(uc.agent_runner, "run", fail)
    assert run_cli(setup_run, monkeypatch, uc) == 4
    folder = setup_run[2].runs_dir / uc.last_run.id
    assert json.loads((folder / "run.json").read_text())["abort_reason"] == reason
    assert f"aborted: {reason}" in (folder / "summary.md").read_text()
    assert main(["show"]) == 4
    output = capsys.readouterr().out
    assert f"aborted: {reason}" in output
    assert "private message" not in output


@pytest.mark.parametrize("boundary", ["Agent", "Browser", "Descriptor", "Scenario"])
def test_adapter_oserror(setup_run, monkeypatch, capsys, boundary):
    uc, _ = usecase(setup_run)

    def fail(*args):
        raise OSError("private message")

    if boundary == "Agent":
        monkeypatch.setattr(uc.agent_runner, "run", fail)
    elif boundary == "Browser":

        class Browser:
            preflight = staticmethod(fail)

        uc.browser_session = Browser()
    elif boundary == "Descriptor":
        monkeypatch.setattr(uc.descriptor_source, "get", fail)
    else:
        monkeypatch.setattr(uc.scenario_source, "load", fail)
    assert uc.execute("demo") == 4
    assert RunStorage(setup_run[2].runs_dir).load()["state"] == "ABORTED"
    output = capsys.readouterr().out
    label = boundary if boundary in ("Agent", "Browser") else "Source"
    assert f"{label} error: aborted: OSError" in output
    assert "storage error" not in output.lower()
    assert "private message" not in output


def test_retry_evidence_isolation(setup_run):
    from aiqa.usecases import JsonVerdictGate

    class Runner:
        calls = 0

        def run(self, scenario, context):
            self.calls += 1
            name = "stale.png" if self.calls == 1 else "final.png"
            (context.output_dir / name).write_bytes(b"synthetic")
            transcript = context.output_dir / "agent.jsonl"
            transcript.write_text(str(self.calls))
            return AgentOutput(
                "bad"
                if self.calls == 1
                else '{"status":"PASSED","summary":"ok","checks":[]}',
                transcript,
            )

    class Gate(JsonVerdictGate):
        def accept(self, scenario, output, transcript, files, caps):
            if caps.output_dir.name == "attempt-2":
                assert {f.name for f in files} == {"final.png", "agent.jsonl"}
            return super().accept(scenario, output, transcript, files, caps)

    uc, _ = usecase(setup_run, verdict_gate=Gate())
    uc.agent_runner = Runner()
    assert uc.execute("demo") == 0
    result = uc.last_run.results[0]
    assert all(
        "stale" not in e.uri and "attempt-1" not in e.uri for e in result.evidence
    )
    folder = setup_run[2].runs_dir / uc.last_run.id / "scenarios/web__test-0"
    assert (folder / "attempt-1/stale.png").exists()
    assert (folder / "attempt-1/agent.jsonl").read_text() == "1"


@pytest.mark.parametrize(
    "at,code",
    [
        (FIXED_TIME, 0),
        (FIXED_TIME + timedelta(days=1), 3),
        (FIXED_TIME + timedelta(days=2), 3),
    ],
)
def test_expiration(setup_run, at, code):
    uc, fake = usecase(setup_run, clock=lambda: at)
    assert uc.execute("demo") == code
    if code == 3:
        assert uc.last_run.refusal_reason == "environment_not_ready"
        assert not fake.calls


def test_start_discards_entry_path_prefix(setup_run):
    d, s, _ = setup_run
    data = descriptor()
    data["entryUrl"] = "https://demo.example/prefix/"
    d.write_text(json.dumps(data))
    data = scenarios(1)
    data["scenarios"][0]["start"] = "/target"
    s.write_text(json.dumps(data))
    uc, fake = usecase(setup_run)
    assert uc.execute("demo") == 0
    assert fake.calls[0][1].start_url == "https://demo.example/target"


@pytest.mark.parametrize("kind", ["descriptor", "scenario", "run"])
def test_deep_json_input_is_invalid(setup_run, monkeypatch, kind):
    d, s, cfg = setup_run
    nested = "[" * 2000 + "0" + "]" * 2000
    if kind == "descriptor":
        d.write_text(nested)
        uc, _ = usecase(setup_run)
        assert uc.execute("demo") == 2
    elif kind == "scenario":
        s.write_text(nested)
        uc, _ = usecase(setup_run)
        assert uc.execute("demo") == 2
    else:
        folder = RunStorage(cfg.runs_dir).create("demo")
        (folder / "run.json").write_text(nested)
        monkeypatch.setenv("AIQA_RUNS_DIR", str(cfg.runs_dir))
        assert main(["show"]) == 2


@pytest.mark.parametrize("kind", ["config", "run", "scenario-file"])
def test_duration_schema_length(kind):
    if kind == "config":
        data = {
            "apiVersion": "ai-qa/v1",
            "budget": {"scenario_timeout": "1" * 11 + "s"},
        }
    elif kind == "run":
        data = Run(
            "demo-20260930T000000Z", "demo", Budget(), "fake", clock=fixed_clock
        ).as_dict()
        data["budget"]["scenario_timeout"] = "1" * 11 + "s"
    else:
        data = scenarios(1)
        data["scenarios"][0]["timeout"] = "1" * 11 + "s"
    with pytest.raises(InvalidInput):
        validate(kind, data)


@pytest.mark.parametrize("at", [FIXED_TIME, datetime(2099, 7, 1, tzinfo=UTC)])
def test_happy_path_independent_of_today(setup_run, monkeypatch, at):
    d, s, cfg = setup_run
    d.write_text(json.dumps(descriptor(at)))
    monkeypatch.setenv("AIQA_RUNS_DIR", str(cfg.runs_dir))
    assert (
        main(
            [
                "run",
                "demo",
                "--agent",
                "fake",
                "--descriptor",
                str(d),
                "--scenarios",
                str(s),
            ],
            clock=lambda: at,
        )
        == 0
    )
    saved = RunStorage(cfg.runs_dir).load()
    assert saved["state"] == "COMPLETED"
    assert len(saved["results"]) == 2
    assert all(result["status"] == "PASSED" for result in saved["results"])


@pytest.mark.parametrize("field", ["createdAt", "expiresAt", "checkedAt"])
@pytest.mark.parametrize("suffix", ["\n", " ", "", "+00:00\n"])
def test_invalid_descriptor_timestamps(setup_run, field, suffix):
    d, _, _ = setup_run
    value = descriptor()
    target = value["readiness"] if field == "checkedAt" else value
    target[field] = FIXED_TIME.replace(tzinfo=None).isoformat() + suffix
    with pytest.raises(InvalidInput):
        EnvironmentDescriptor.parse(value)
    d.write_text(json.dumps(value))
    uc, fake = usecase(setup_run)
    assert uc.execute("demo") == 2
    assert uc.last_run.refusal_reason == "invalid_descriptor"
    assert not fake.calls


def test_yaml_unquoted_timestamps(setup_run):
    import yaml

    d, s, cfg = setup_run
    value = descriptor()
    # Dump datetime values to produce unquoted ISO timestamp scalars.
    for field in ("createdAt", "expiresAt"):
        value[field] = datetime.fromisoformat(value[field])
    value["readiness"]["checkedAt"] = FIXED_TIME
    yaml_path = d.with_suffix(".yaml")
    yaml_path.write_text(yaml.safe_dump(value).replace(" 00:00:00", "T00:00:00"))
    uc, fake = usecase((yaml_path, s, cfg))
    assert uc.execute("demo") == 0
    assert len(fake.calls) == 2
    assert uc.last_run.state == "COMPLETED"


def test_yaml_scenario_and_config_dates_remain_strings(tmp_path):
    scenario_path = tmp_path / "scenarios.yaml"
    scenario_path.write_text(
        "apiVersion: ai-qa/v1\nscenarios:\n"
        "  - id: date-test\n    title: 2040-01-15\n"
        "    steps: [2040-01-15]\n    expect: [2040-01-15]\n"
    )
    scenario = parse_scenarios(load_yaml(scenario_path), "web")[0]
    assert scenario.title == "2040-01-15"
    assert scenario.steps == scenario.expect == ("2040-01-15",)
    config_path = tmp_path / "config.yaml"
    config_path.write_text("apiVersion: ai-qa/v1\nagent:\n  model: 2040-01-15\n")
    assert Config.load(config_path, environ={}).agent_model == "2040-01-15"


@pytest.mark.parametrize(
    "bad",
    [
        "[" * 2000 + "0" + "]" * 2000,
        '{"status":"PASSED","summary":"ok","checks":[[[0]]]}',
    ],
)
def test_bad_agent_json_is_scenario_local(setup_run, bad):
    uc, fake = usecase(setup_run, [AgentOutput(bad), AgentOutput(bad)])
    assert uc.execute("demo") == 1
    assert len(fake.calls) == 3
    assert uc.last_run.state == "COMPLETED"
    assert [r.reason for r in uc.last_run.results] == ["agent_protocol", None]
    assert uc.last_run.results[1].status == "PASSED"


@pytest.mark.parametrize("field", ["summary", "expect", "observed"])
@pytest.mark.parametrize("text", ["\ud800", "\x00", "\r", "\x7f", "\x85", "x" * 501])
def test_bad_agent_strings_are_scenario_local(setup_run, field, text):
    value = {
        "status": "PASSED",
        "summary": "ok",
        "checks": [{"expect": "Visible", "ok": True, "observed": "Visible"}],
    }
    if field == "summary":
        value[field] = text
    else:
        value["checks"][0][field] = text
    bad = AgentOutput(json.dumps(value))
    uc, fake = usecase(setup_run, [bad, bad])
    assert uc.execute("demo") == 1
    assert len(fake.calls) == 3
    assert uc.last_run.state == "COMPLETED"
    assert uc.last_run.results[0].reason == "agent_protocol"
    assert uc.last_run.results[1].status == "PASSED"


@pytest.mark.parametrize(
    "error", [RuntimeError, RecursionError, KeyError, UnicodeEncodeError]
)
def test_unexpected_gate_interpretation_is_scenario_local(setup_run, error):
    from aiqa.usecases import JsonVerdictGate

    class Gate(JsonVerdictGate):
        def accept(self, scenario, output, transcript, files, caps):
            if scenario.id == "test-0":
                if error is UnicodeEncodeError:
                    raise error("utf-8", "\ud800", 0, 1, "surrogate")
                raise error()
            return super().accept(scenario, output, transcript, files, caps)

    uc, fake = usecase(setup_run, verdict_gate=Gate())
    assert uc.execute("demo") == 1
    assert len(fake.calls) == 3
    assert uc.last_run.state == "COMPLETED"
    assert uc.last_run.results[0].reason == "agent_protocol"
    assert uc.last_run.results[1].status == "PASSED"


def test_agent_text_allows_utf8_newlines_tabs_and_limit(setup_run):
    text = "한\n\t" + "x" * 497
    value = {
        "status": "PASSED",
        "summary": text,
        "checks": [{"expect": text, "ok": True, "observed": text}],
    }
    uc, _ = usecase(setup_run, [AgentOutput(json.dumps(value))])
    assert uc.execute("demo") == 0
    stored = uc.storage.load(uc.last_run.id)
    assert stored["results"][0]["summary"] == text
    assert stored["results"][0]["checks"] == value["checks"]


def test_storage_escapes_unencodable_text(tmp_path):
    from aiqa.storage import write_json

    path = tmp_path / "text.txt"
    atomic_write(path, "한\ud800")
    assert path.read_text() == "한\\ud800"
    write_json(path, {"text": "한\ud800"})
    assert json.loads(path.read_text()) == {"text": "한\ud800"}


def test_one_clock_governs_all_run_timestamps(setup_run):
    times = iter([FIXED_TIME, FIXED_TIME, FIXED_TIME + timedelta(seconds=7)])
    uc, _ = usecase(setup_run, clock=lambda: next(times))
    assert uc.execute("demo") == 0
    assert uc.last_run.id == "demo-20400115T000000Z"
    data = uc.storage.load(uc.last_run.id)
    report_data = json.loads(
        (uc.storage.root / uc.last_run.id / "report.json").read_text()
    )
    assert data["started_at"] == report_data["startedAt"] == FIXED_TIME.isoformat()
    assert (
        data["finished_at"]
        == report_data["finishedAt"]
        == (FIXED_TIME + timedelta(seconds=7)).isoformat()
    )
    with pytest.raises(StopIteration):
        next(times)


@pytest.mark.parametrize("content", ["[" * 2000 + "0" + "]" * 2000, "9" * 5000])
def test_numeric_and_nested_user_json_are_invalid_input(setup_run, content):
    setup_run[0].write_text(content)
    uc, fake = usecase(setup_run)
    assert uc.execute("demo") == 2
    assert not fake.calls


def test_surrogate_in_saved_run_is_invalid_input(tmp_path):
    from aiqa.storage import write_json

    storage = RunStorage(tmp_path)
    path = storage.create("demo", fixed_clock())
    run = Run(path.name, "demo", Budget(), "fake", clock=fixed_clock).as_dict()
    run["agent"]["model"] = "\ud800"
    write_json(path / "run.json", run)
    with pytest.raises(InvalidInput):
        storage.load(path.name)


@pytest.mark.parametrize(
    "field,bad",
    [
        ("seconds", "bad"),
        pytest.param("seconds", -(10**5000), id="negative-huge-seconds"),
        pytest.param("seconds", 10**5000, id="huge-seconds"),
        ("seconds", float("nan")),
        ("seconds", float("inf")),
        ("seconds", True),
        pytest.param("turns", 10**5000, id="huge-turns"),
        ("turns", "bad"),
        ("transcript_path", "bad"),
        ("transcript_path", Path("\ud800")),
    ],
)
def test_invalid_agent_metadata_is_scenario_local(setup_run, field, bad):
    output = replace(AgentOutput("bad"), **{field: bad})
    uc, fake = usecase(setup_run, [output, output])
    assert uc.execute("demo") == 1
    assert len(fake.calls) == 3
    assert uc.last_run.state == "COMPLETED"
    assert uc.last_run.results[0].reason == "agent_protocol"
    assert uc.last_run.results[1].status == "PASSED"


@pytest.mark.parametrize("field", ["AIQA_RUNS_DIR", "AIQA_STATE_FILE"])
@pytest.mark.parametrize(
    "path", ["invalid\x00path", "~aiqa-no-such-synthetic-user/path"]
)
def test_bad_configured_paths_are_invalid_input(field, path):
    with pytest.raises(InvalidInput):
        Config.parse({"apiVersion": "ai-qa/v1"}, {field: path})


def test_oversized_yaml_number_is_invalid_input(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("value: " + "9" * 5000)
    with pytest.raises(InvalidInput):
        load_yaml(path)


@pytest.mark.parametrize("content", ["null", "[]", "[" * 2000 + "0" + "]" * 2000])
def test_abort_recovery_handles_corrupt_user_run_file(setup_run, content):
    uc, _ = usecase(setup_run)

    class Runner:
        def run(self, scenario, context):
            (context.output_dir.parents[2] / "run.json").write_text(content)
            raise OSError("synthetic infrastructure failure")

    uc.agent_runner = Runner()
    assert uc.execute("demo") == 4
    assert uc.last_run.state == "ABORTED"


def test_gate_invalid_evidence_uri_is_scenario_local(setup_run):
    from aiqa.run import Evidence
    from aiqa.usecases import JsonVerdictGate

    class Gate(JsonVerdictGate):
        def accept(self, scenario, output, transcript, files, caps):
            result = super().accept(scenario, output, transcript, files, caps)
            if scenario.id == "test-0":
                return replace(result, evidence=(Evidence("log", "bad\x00path"),))
            return result

    uc, fake = usecase(setup_run, verdict_gate=Gate())
    assert uc.execute("demo") == 1
    assert len(fake.calls) == 3
    assert uc.last_run.state == "COMPLETED"
    assert uc.last_run.results[0].reason == "agent_protocol"
    assert uc.last_run.results[1].status == "PASSED"


@pytest.mark.parametrize("transcript", [False, True])
def test_control_character_auto_evidence_is_scenario_local(setup_run, transcript):
    class Runner(FakeAgentRunner):
        def run(self, scenario, context):
            output = super().run(scenario, context)
            bad = context.output_dir / ("agent\n.jsonl" if transcript else "a\n.png")
            bad.write_text("synthetic")
            return replace(output, transcript_path=bad) if transcript else output

    uc, _ = usecase(setup_run)
    uc.agent_runner = Runner()
    assert uc.execute("demo") == (1 if transcript else 0)
    assert uc.last_run.state == "COMPLETED"
    for result in uc.last_run.results:
        assert all("\n" not in e.uri for e in result.evidence)
        if transcript:
            assert result.reason == "agent_protocol"
        else:
            assert result.status == "PASSED"
            assert result.evidence  # the valid transcript remains


@pytest.mark.parametrize(
    "value", ["host/path", "user@host", " host", "host\n", "https://host", "host:443"]
)
def test_access_team_requires_plain_hostname(value):
    with pytest.raises(InvalidInput):
        Config.parse({"apiVersion": "ai-qa/v1", "hub": {"access_team_domain": value}})


@pytest.mark.parametrize(
    "value",
    [
        "http://host",
        "https://user@host",
        "https://host/path with space",
        "https://host\n",
    ],
)
def test_dashboard_requires_https_without_userinfo_or_whitespace(value):
    with pytest.raises(InvalidInput):
        Config.parse({"apiVersion": "ai-qa/v1", "hub": {"dashboard_url": value}})


@pytest.mark.parametrize("state", ["CREATED", "PREFLIGHT", "RUNNING"])
def test_show_live_run_returns_in_progress(tmp_path, monkeypatch, capsys, state):
    storage = RunStorage(tmp_path)
    folder = storage.create("demo", fixed_clock())
    run = Run(folder.name, "demo", Budget(), "fake", clock=fixed_clock)
    if state != "CREATED":
        run.transition("PREFLIGHT")
    if state == "RUNNING":
        run.start({"web": "a" * 40}, ["web/test-0"])
    storage.save(run)
    monkeypatch.setenv("AIQA_RUNS_DIR", str(tmp_path))
    assert main(["show"]) == 5
    assert state in capsys.readouterr().out


@pytest.mark.parametrize(
    "uri",
    [
        "/tmp/file.png",
        "scenarios/web__test-0/../file.png",
        "scenarios/web__test-1/file.png",
        "x" * 4097,
    ],
)
def test_gate_evidence_must_stay_in_scenario(setup_run, uri):
    from aiqa.run import Evidence
    from aiqa.usecases import JsonVerdictGate

    class Gate(JsonVerdictGate):
        def accept(self, scenario, output, transcript, files, caps):
            result = super().accept(scenario, output, transcript, files, caps)
            if scenario.id == "test-0":
                return replace(result, evidence=(Evidence("log", uri),))
            return result

    uc, _ = usecase(setup_run, verdict_gate=Gate())
    assert uc.execute("demo") == 1
    assert uc.last_run.state == "COMPLETED"
    assert uc.last_run.results[0].reason == "agent_protocol"
    assert uc.last_run.results[1].status == "PASSED"


def test_nonfinite_gate_result_is_scenario_local(setup_run):
    from aiqa.usecases import JsonVerdictGate

    class Gate(JsonVerdictGate):
        def accept(self, scenario, output, transcript, files, caps):
            result = super().accept(scenario, output, transcript, files, caps)
            return (
                replace(result, seconds=float("nan"))
                if scenario.id == "test-0"
                else result
            )

    uc, _ = usecase(setup_run, verdict_gate=Gate())
    assert uc.execute("demo") == 1
    assert uc.last_run.state == "COMPLETED"
    assert uc.last_run.results[0].reason == "agent_protocol"


def test_config_model_rejects_control_characters():
    with pytest.raises(InvalidInput):
        Config.parse({"apiVersion": "ai-qa/v1", "agent": {"model": "bad\nmodel"}})


@pytest.mark.parametrize("name", ["AIQA_CONFIG", "AIQA_RUNS_DIR", "AIQA_STATE_FILE"])
@pytest.mark.parametrize("value", ["", " \t\n"])
def test_blank_environment_paths_are_unset(tmp_path, monkeypatch, name, value):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "aiqa.yaml").write_text(
        "apiVersion: ai-qa/v1\nruns_dir: configured-runs\nbudget:\n  max_turns: 2\n"
    )
    assert Config.load(environ={name: value}) == Config.load(environ={})
    assert Config.load(environ={name: value}).max_turns == 2


@pytest.mark.parametrize("directory", [False, True])
def test_agent_attempt_name_does_not_collide_with_retry(setup_run, directory):
    from aiqa.usecases import JsonVerdictGate

    class Runner:
        calls = 0

        def run(self, scenario, context):
            self.calls += 1
            collision = context.output_dir / "attempt-1"
            if directory:
                collision.mkdir()
                (collision / "nested.txt").write_text("synthetic")
            else:
                collision.write_text("synthetic")
            return AgentOutput("bad" if self.calls == 1 else '{"status":"PASSED"}')

    class Gate(JsonVerdictGate):
        def accept(self, scenario, output, transcript, files, caps):
            assert caps.output_dir / "attempt-1" in files
            return super().accept(scenario, output, transcript, files, caps)

    uc, _ = usecase(setup_run, verdict_gate=Gate())
    runner = Runner()
    uc.agent_runner = runner
    assert uc.execute("demo") == 0
    assert runner.calls == 3
    assert uc.last_run.state == "COMPLETED"
    assert all(r.status == "PASSED" for r in uc.last_run.results)


@pytest.mark.parametrize("operation", ["list", "gate", "evidence", "resolve"])
def test_agent_file_errors_fail_only_scenario(setup_run, monkeypatch, operation):
    from aiqa.usecases import JsonVerdictGate

    original_iterdir = Path.iterdir
    original_is_file = Path.is_file
    original_resolve = Path.resolve

    def fail_resolve(path, *args, **kwargs):
        if "web__test-0" in path.parts and path.name == "agent.jsonl":
            raise PermissionError("synthetic")
        return original_resolve(path, *args, **kwargs)

    def fail_iterdir(path):
        if "web__test-0" in path.parts and path.name == "attempt-1":
            raise PermissionError("synthetic")
        return original_iterdir(path)

    def fail_is_file(path):
        if "web__test-0" in path.parts and path.name == "agent.jsonl":
            raise PermissionError("synthetic")
        return original_is_file(path)

    class Gate(JsonVerdictGate):
        def accept(self, scenario, output, transcript, files, caps):
            if operation == "gate" and scenario.id == "test-0":
                raise PermissionError("synthetic")
            return super().accept(scenario, output, transcript, files, caps)

    if operation == "list":
        monkeypatch.setattr(Path, "iterdir", fail_iterdir)
    elif operation == "evidence":
        monkeypatch.setattr(Path, "is_file", fail_is_file)
    if operation == "resolve":
        monkeypatch.setattr(Path, "resolve", fail_resolve)
    uc, _ = usecase(setup_run, verdict_gate=Gate())
    assert uc.execute("demo") == 1
    assert uc.last_run.state == "COMPLETED"
    assert uc.last_run.results[0].reason == "agent_error"
    assert uc.last_run.results[1].status == "PASSED"


def test_unknown_browser_refusal_aborts(setup_run, monkeypatch, capsys):
    class Browser:
        def preflight(self, url):
            raise Refused("not-in-enum")

    uc, fake = usecase(setup_run, browser_session=Browser())
    assert run_cli(setup_run, monkeypatch, uc) == 4
    saved = uc.storage.load()
    assert saved["state"] == "ABORTED"
    assert saved["abort_reason"] == "Browser: ValueError"
    assert saved["refusal_reason"] is None
    assert not fake.calls
    assert (
        "State: ABORTED" in (uc.storage.root / saved["id"] / "summary.md").read_text()
    )
    assert "ABORTED" in capsys.readouterr().out


@pytest.mark.parametrize("handler", ["refused", "invalid"])
@pytest.mark.parametrize("error", [InvalidInput, OSError, RuntimeError])
def test_handler_save_invalid_input_recovers(setup_run, monkeypatch, handler, error):
    class Browser:
        def preflight(self, url):
            if handler == "refused":
                raise Refused("login_required")
            raise InvalidInput("synthetic")

    uc, _ = usecase(setup_run, browser_session=Browser())
    original = uc.storage.save

    def save(run):
        if run.state == "REFUSED":
            raise error("synthetic save failure")
        original(run)

    monkeypatch.setattr(uc.storage, "save", save)
    assert run_cli(setup_run, monkeypatch, uc) == 4
    assert uc.storage.load()["state"] == "ABORTED"


@pytest.mark.parametrize(
    "case,valid",
    [
        ("nested", True),
        ("http", True),
        ("missing", False),
        ("directory", False),
        ("escape", False),
        ("previous", False),
        ("foreign_http", False),
        ("ftp", False),
        ("unknown", False),
    ],
)
def test_gate_evidence_rule(setup_run, case, valid):
    from aiqa.run import Evidence
    from aiqa.usecases import JsonVerdictGate

    class Gate(JsonVerdictGate):
        def accept(self, scenario, output, transcript, files, caps):
            result = super().accept(scenario, output, transcript, files, caps)
            target = caps.output_dir / "nested" / "proof.log"
            target.parent.mkdir()
            target.write_text("synthetic")
            kind = "log"
            uri = target.relative_to(
                setup_run[2].runs_dir / caps.output_dir.parents[2].name
            ).as_posix()
            if case == "http":
                kind, uri = "http", "https://demo.example/proof"
            elif case == "foreign_http":
                kind, uri = "http", "https://other.example/proof"
            elif case == "ftp":
                kind, uri = "http", "ftp://demo.example/proof"
            elif case == "unknown":
                kind = "other"
            elif case == "missing":
                target.unlink()
            elif case == "directory":
                target.unlink()
                target.mkdir()
            elif case == "escape":
                target.unlink()
                target.symlink_to(setup_run[0])
            elif case == "previous":
                uri = uri.replace("attempt-1", "attempt-0")
            return replace(result, evidence=(Evidence(kind, uri),))

    uc, _ = usecase(
        setup_run, config=replace(setup_run[2], protocol_retries=0), verdict_gate=Gate()
    )
    assert uc.execute("demo") == (0 if valid else 1)
    result = uc.last_run.results[0]
    if valid:
        assert result.evidence[0].type == ("http" if case == "http" else "log")
        assert result.evidence[0].uri.endswith(
            "/proof" if case == "http" else "/proof.log"
        )
    else:
        assert result.reason == "agent_protocol"


@pytest.mark.parametrize("content", [None, "{}", "not json", "\\xff"])
def test_completed_without_valid_report_is_interrupted(setup_run, monkeypatch, content):
    uc, _ = usecase(setup_run)
    assert uc.execute("demo") == 0
    path = uc.storage.root / uc.last_run.id / "report.json"
    if content is None:
        path.unlink()
    else:
        path.write_text(content)
    assert uc.storage.load()["state"] == "INTERRUPTED"
    monkeypatch.setenv("AIQA_RUNS_DIR", str(uc.storage.root))
    assert main(["show"]) == 4
