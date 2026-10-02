import json
import os
from types import SimpleNamespace

import pytest

from aiqa.agents.claude import ClaudeCodeRunner
from aiqa.browser import ServiceTokenPreflight
from aiqa.cli import main
from aiqa.contracts import Config
from aiqa.redact import Redactor
from aiqa.storage import RunStorage
from aiqa.usecases import Refused


@pytest.mark.parametrize("http_only", [True, False])
@pytest.mark.parametrize("mixed_case", [False, True])
def test_service_exchange_origin_headers_and_state(tmp_path, http_only, mixed_case):
    token = tmp_path / "token.json"
    token.write_text(
        json.dumps(
            {
                "client_id": "synthetic-client-id-123456",
                "client_secret": "synthetic-secret-123456789",
            }
        )
    )
    calls = []
    state = {
        "cookies": [
            {
                "name": "CF_Authorization",
                "value": "synthetic-cookie",
                "domain": "PHUB-DEMO.CAFITAC.COM"
                if mixed_case
                else "phub-demo.cafitac.com",
                "httpOnly": http_only,
            },
            {
                "name": "CF_AppSession",
                "value": "synthetic-sibling-cookie",
                "domain": "team.example",
                "httpOnly": False,
            },
            {
                "name": "unrelated",
                "value": "data",
                "domain": "phub-demo.cafitac.com",
                "httpOnly": True,
            },
            {
                "name": "CF_Authorization",
                "value": "foreign",
                "domain": "foreign.example",
                "httpOnly": True,
            },
        ],
        "origins": [
            {
                "origin": "https://phub-demo.cafitac.com",
                "localStorage": [{"name": "secret", "value": "data"}],
            }
        ],
    }

    class Request:
        def get(self, url, **kwargs):
            calls.append((url, kwargs))
            redirects = [
                "https://TEAM.EXAMPLE/login"
                if mixed_case
                else "https://team.example/login",
                "https://PHUB-DEMO.CAFITAC.COM/"
                if mixed_case
                else "https://phub-demo.cafitac.com/",
            ]
            index = len(calls) - 1
            return SimpleNamespace(
                status=302 if index < 2 else 200,
                headers={"location": redirects[index]} if index < 2 else {},
                dispose=lambda: None,
            )

        def storage_state(self):
            return state

        def dispose(self):
            pass

    class Factory:
        def __enter__(self):
            return SimpleNamespace(request=SimpleNamespace(new_context=Request))

        def __exit__(self, *args):
            pass

    config = Config(
        service_token_file=token,
        access_mode="service_token",
        access_team_domain="Team.Example" if mixed_case else "team.example",
    )
    with ServiceTokenPreflight(config, Factory) as session:
        session.origins = ("https://phub-demo.cafitac.com",)
        if not http_only:
            with pytest.raises(Refused, match="HttpOnly"):
                session.preflight("https://phub-demo.cafitac.com/")
        else:
            path = session.preflight("https://phub-demo.cafitac.com/")
            assert json.loads(path.read_text()) == {
                "cookies": state["cookies"][:1],
                "origins": [],
            }
            assert path.stat().st_mode & 0o777 == 0o600
    assert calls[0][1]["headers"]["CF-Access-Client-Id"] == "synthetic-client-id-123456"
    assert all(not kwargs["headers"] for _, kwargs in calls[1:])
    assert all(kwargs["max_redirects"] == 0 for _, kwargs in calls)
    if http_only:
        assert not path.exists()


def test_child_environment_and_redaction(tmp_path, monkeypatch):
    claude = tmp_path / "claude"
    access = tmp_path / "access.json"
    values = (
        "claude" + "c" * 14,
        "client" + "i" * 14,
        "secret" + "s" * 14,
    )
    claude.write_text(values[0])
    access.write_text(
        json.dumps(dict(zip(("client_id", "client_secret"), values[1:], strict=True)))
    )
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    config = Config(
        claude_token_file=claude, service_token_file=access, access_mode="service_token"
    )
    assert (
        ClaudeCodeRunner(config).child_environment()["CLAUDE_CODE_OAUTH_TOKEN"]
        == values[0]
    )
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in os.environ
    redactor = Redactor.from_state(None, config=config)
    for index, secret in enumerate(values):
        log = tmp_path / f"leak-{index}.log"
        log.write_text(secret)
        assert redactor.scan(tmp_path)
        assert not log.exists()


def test_run_id_file_and_prune(tmp_path, monkeypatch):
    from test_core import descriptor, fixed_clock

    monkeypatch.chdir(tmp_path)
    (tmp_path / "descriptor.json").write_text(json.dumps(descriptor()))
    (tmp_path / "scenarios.yaml").write_text("apiVersion: ai-qa/v1\nscenarios: []\n")
    run_id_file = tmp_path / "inbox" / "runid"
    assert (
        main(
            [
                "run",
                "demo",
                "--agent",
                "fake",
                "--descriptor",
                "descriptor.json",
                "--scenarios",
                "scenarios.yaml",
                "--run-id-file",
                str(run_id_file),
            ],
            clock=fixed_clock,
        )
        == 3
    )
    run_id = run_id_file.read_text().strip()
    storage = RunStorage(tmp_path / "runs")
    assert (storage.root / run_id / "run.json").exists()
    unrelated = storage.root / "inbox"
    unrelated.mkdir()
    link = storage.root / "other-20260101T000000Z"
    link.symlink_to(unrelated, target_is_directory=True)
    assert storage.prune(1) == []
    assert storage.prune(0) == [run_id]
    assert unrelated.is_dir() and link.is_symlink()
    assert Config.parse({"apiVersion": "ai-qa/v1"}, {}).access_mode == "session"


@pytest.mark.parametrize("version", [None, "1.2.3", "0.0.83"])
def test_runner_passes_token_only_in_child_env(tmp_path, monkeypatch, version):
    from aiqa.contracts import Scenario
    from aiqa.ports import AgentContext

    installed = version == "1.2.3"
    package_dir = tmp_path / "node_modules" / "@playwright" / "mcp"
    package_dir.mkdir(parents=True)
    binary = package_dir / "cli.js"
    binary.write_text("// synthetic executable")
    (package_dir / "package.json").write_text(
        json.dumps({"name": "@playwright/mcp", "version": version})
    )
    link = tmp_path / "playwright-mcp"
    link.symlink_to(binary)
    token = "synthetic-child-token-123456"
    token_file = tmp_path / "token"
    token_file.write_text(token)
    state = tmp_path / "state.json"
    state.write_text('{"cookies": []}')
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    seen = {}

    class Process:
        returncode = 0

        def wait(self, **kwargs):
            pass

    def launcher(command, **kwargs):
        seen.update(kwargs)
        from pathlib import Path

        mcp = json.loads(Path(command[command.index("--mcp-config") + 1]).read_text())[
            "mcpServers"
        ]["playwright"]
        assert mcp["command"] == ("playwright-mcp" if installed else "npx")
        assert ("@playwright/mcp@1.2.3" in mcp["args"]) == (not installed)
        assert token not in str(command)
        kwargs["stdout"].write(b'{"type":"result","result":"{}"}\n')
        return Process()

    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.setattr(
        "aiqa.agents.claude.shutil.which",
        lambda name: str(link) if version else None,
    )
    monkeypatch.setattr("aiqa.agents.claude.terminate_group", lambda process: None)
    ClaudeCodeRunner(
        Config(claude_token_file=token_file, playwright_mcp="@playwright/mcp@1.2.3"),
        launcher,
    ).run(
        Scenario("test-it", "Test", "web", ("Click",), ("Visible",)),
        AgentContext(
            output_dir,
            "https://phub-demo.cafitac.com/",
            ("https://phub-demo.cafitac.com",),
            2,
            10,
            storage_state=state,
        ),
    )
    assert seen["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == token
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in os.environ


def test_prune_orders_across_environments(tmp_path):
    from datetime import UTC, datetime

    from aiqa.run import Budget, Run

    storage = RunStorage(tmp_path)
    ids = []
    for day, environment in ((1, "zz"), (2, "aa"), (3, "mm")):
        path = storage.create(environment, datetime(2026, 1, day, tzinfo=UTC))
        run = Run(path.name, environment, Budget(), "claude")
        run.transition("PREFLIGHT")
        run.refusal_reason = "no_scenarios"
        run.transition("REFUSED")
        storage.save(run)
        ids.append(path.name)
    assert storage.prune(2) == [ids[0]]
    assert storage.list() == list(reversed(ids[1:]))


@pytest.mark.parametrize("browser", [None, "chromium"])
def test_mcp_browser_override(tmp_path, browser):
    from aiqa.agents.claude import mcp_args
    from aiqa.ports import AgentContext

    context = AgentContext(
        tmp_path,
        "https://example.com",
        ("https://example.com",),
        2,
        10,
        storage_state=tmp_path / "state",
    )
    config = Config.parse(
        {"apiVersion": "ai-qa/v1"}, {"AIQA_AGENT_BROWSER": browser} if browser else {}
    )
    args = mcp_args(config, context)
    assert ("--browser" in args) == bool(browser)
    if browser:
        assert args[args.index("--browser") + 1] == browser
    assert (
        Config.parse(
            {"apiVersion": "ai-qa/v1", "agent": {"browser": "chromium"}}, {}
        ).agent_browser
        == "chromium"
    )


@pytest.mark.parametrize("service", [False, True])
def test_invalid_utf8_secret(tmp_path, service):
    from aiqa.contracts import InvalidInput
    from aiqa.secrets import read_secret

    path = tmp_path / "invalid"
    path.write_bytes(b"synthetic-secret-\xff")
    with pytest.raises(InvalidInput, match="^Secret file is unreadable or invalid$"):
        read_secret(path, service=service)
    config = Config(claude_token_file=path)
    with pytest.raises(InvalidInput):
        ClaudeCodeRunner(config).child_environment()
    with pytest.raises(InvalidInput):
        Redactor.from_state(None, config=config)


@pytest.mark.parametrize("service", [False, True])
@pytest.mark.parametrize("environment", [False, True])
def test_null_secret_paths(service, environment):
    from aiqa.contracts import InvalidInput

    config = {"apiVersion": "ai-qa/v1"}
    env = {}
    if environment:
        env["AIQA_SERVICE_TOKEN_FILE" if service else "AIQA_CLAUDE_TOKEN_FILE"] = (
            "synthetic\x00path"
        )
    else:
        config["access" if service else "agent"] = {
            "service_token_file" if service else "token_file": "synthetic\x00path"
        }
    with pytest.raises(InvalidInput):
        Config.parse(config, env)


def test_invalid_secret_refused_before_agent(tmp_path):
    from test_core import descriptor, fixed_clock

    from aiqa.usecases import RunScenarios

    secret = tmp_path / "secret"
    secret.write_bytes(b"\xff")
    calls = []
    runner = SimpleNamespace(run=lambda *args: calls.append(args))
    source = SimpleNamespace(get=lambda *args: descriptor())
    usecase = RunScenarios(
        source,
        SimpleNamespace(),
        runner,
        Config(
            runs_dir=tmp_path / "runs",
            service_token_file=secret,
            access_mode="service_token",
        ),
        clock=fixed_clock,
    )
    assert usecase.execute("demo") == 3
    assert not calls
    assert usecase.last_run.state == "REFUSED"
    assert usecase.last_run.refusal_reason == "login_required"


def test_cached_secret_redaction(tmp_path):
    from aiqa.secrets import RunSecrets

    path = tmp_path / "token"
    value = "synthetic-cached-secret-123456"
    path.write_text(value)
    config = Config(claude_token_file=path)
    secrets = RunSecrets.load(config)
    path.unlink()
    runner = ClaudeCodeRunner(config)
    runner.secrets = secrets
    assert runner.child_environment()["CLAUDE_CODE_OAUTH_TOKEN"] == value
    redactor = Redactor.from_state(None, loaded_secrets=secrets)
    (tmp_path / "leak").write_text(value)
    assert redactor.scan(tmp_path)


@pytest.mark.parametrize("content", [b"not json", b"\xff", b"{}"])
def test_prune_skips_invalid_record(tmp_path, content, capsys, monkeypatch):
    run_id = "demo-20260101T000000Z"
    path = tmp_path / run_id
    path.mkdir()
    (path / "run.json").write_bytes(content)
    storage = RunStorage(tmp_path)
    assert storage.prune(0) == []
    assert storage.prune_skipped == [run_id]
    assert path.exists()
    monkeypatch.setenv("AIQA_RUNS_DIR", str(tmp_path))
    assert main(["prune", "--keep", "0"]) == 0
    assert f"skipped: {run_id}" in capsys.readouterr().out


def test_prune_skips_unreadable_record(tmp_path, monkeypatch):
    from aiqa.contracts import InvalidInput

    run_id = "demo-20260101T000000Z"
    path = tmp_path / run_id
    path.mkdir()
    (path / "run.json").write_text("{}")
    storage = RunStorage(tmp_path)

    def unreadable(*args, **kwargs):
        raise InvalidInput("Cannot load run")

    monkeypatch.setattr(storage, "load", unreadable)
    assert storage.prune(0) == []
    assert storage.prune_skipped == [run_id]
    assert path.exists()


def test_prune_concurrent_removal(tmp_path, monkeypatch):
    import shutil

    run_id = "demo-20260101T000000Z"
    path = tmp_path / run_id
    path.mkdir()
    (path / "run.json").write_text("{}")
    storage = RunStorage(tmp_path)
    monkeypatch.setattr(storage, "load", lambda *args, **kwargs: {"state": "COMPLETED"})
    remove = shutil.rmtree

    def raced_remove(directory):
        remove(directory)
        raise FileNotFoundError

    monkeypatch.setattr("aiqa.storage.shutil.rmtree", raced_remove)
    assert storage.prune(0) == []
    assert storage.prune_skipped == []
    assert not path.exists()


@pytest.mark.parametrize(
    "manifest", [None, "not json", '{"name":"other","version":"1.2.3"}']
)
def test_installed_mcp_requires_package_identity(tmp_path, manifest):
    from aiqa.agents.claude import installed_mcp_matches

    binary = tmp_path / "cli.js"
    binary.write_text("// synthetic executable")
    if manifest is not None:
        (tmp_path / "package.json").write_text(manifest)
    assert not installed_mcp_matches(str(binary), "@playwright/mcp@1.2.3")


def test_redaction_keeps_cookie_length_filter(tmp_path):
    from aiqa.secrets import RunSecrets

    state = tmp_path / "state.json"
    state.write_text(
        json.dumps(
            {"cookies": [{"name": "CF_Authorization", "value": "cookie1234567"}]}
        )
    )
    redactor = Redactor.from_state(
        state, loaded_secrets=RunSecrets(claude="secret123456")
    )
    state.unlink()
    cookie_log = tmp_path / "cookie.log"
    cookie_log.write_text("cookie1234567")
    secret_log = tmp_path / "secret.log"
    secret_log.write_text("secret123456")
    assert redactor.scan(tmp_path)
    assert cookie_log.exists()
    assert not secret_log.exists()


@pytest.mark.parametrize("field", ["claude", "client_id", "client_secret"])
@pytest.mark.parametrize("length", [1, 12, 19])
def test_short_secret_refused(tmp_path, field, length):
    from aiqa.contracts import InvalidInput
    from aiqa.secrets import RunSecrets

    value = "x" * length
    path = tmp_path / "token"
    if field == "claude":
        path.write_text(value)
        config = Config(claude_token_file=path)
    else:
        data = {"client_id": "i" * 20, "client_secret": "s" * 20}
        data[field] = value
        path.write_text(json.dumps(data))
        config = Config(service_token_file=path, access_mode="service_token")
    with pytest.raises(InvalidInput) as exc:
        RunSecrets.load(config)
    assert str(exc.value) == "Secret file is unreadable or invalid"
    with pytest.raises(InvalidInput):
        Redactor.from_state(None, config=config)


def test_unwritable_run_id_preserves_aborted_run(tmp_path):
    from test_core import fixed_clock

    from aiqa.usecases import RunScenarios

    blocked = tmp_path / "blocked"
    blocked.write_text("synthetic obstruction")
    usecase = RunScenarios(
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
        Config(runs_dir=tmp_path / "runs"),
        clock=fixed_clock,
        run_id_file=blocked / "runid",
    )
    assert usecase.execute("demo") == 4
    assert usecase.last_run is not None
    storage = usecase.storage
    assert storage.list() == [usecase.last_run.id]
    saved = storage.load(usecase.last_run.id, check_liveness=False)
    assert saved["state"] == "ABORTED"
    assert saved["abort_reason"] == "FileExistsError"
    assert storage.prune(0) == [usecase.last_run.id]


def test_session_login_still_refuses_non_http_only_sibling(tmp_path):
    from test_adapters import FakePlaywright

    from aiqa.browser import PlaywrightSession

    class SiblingPlaywright(FakePlaywright):
        def storage_state(self):
            state = super().storage_state()
            state["cookies"].append(
                {
                    "name": "CF_AppSession",
                    "value": "synthetic-sibling-cookie",
                    "domain": "team.example",
                    "httpOnly": False,
                }
            )
            return state

    config = Config(
        dashboard_url="https://demo.example/",
        access_team_domain="team.example",
        state_file=tmp_path / "state.json",
    )
    fake = SiblingPlaywright()
    with pytest.raises(Refused, match="HttpOnly"):
        PlaywrightSession(config, lambda: fake).login()
    assert not config.state_file.exists() and fake.closed


def test_unused_secret_files_are_not_read(tmp_path):
    from aiqa.secrets import RunSecrets

    broken = tmp_path / "broken"
    broken.write_bytes(b"\xff")
    config = Config(claude_token_file=broken, service_token_file=broken)
    assert RunSecrets.load(config, claude=False) == RunSecrets()
    service = Config(
        claude_token_file=broken,
        service_token_file=broken,
        access_mode="service_token",
    )
    from aiqa.contracts import InvalidInput

    with pytest.raises(InvalidInput):
        RunSecrets.load(service, claude=False)


@pytest.mark.parametrize(
    "entry",
    [
        "https://attacker.example/",
        "https://phub-demo.cafitac.com.attacker.example/",
        "https://phub-demo.cafitac.com:8443/",
        "https://preview-hub.cafitac.com/",
    ],
)
def test_service_credentials_only_sent_to_environment_hosts(tmp_path, entry):
    token = tmp_path / "token.json"
    token.write_text(
        json.dumps(
            {
                "client_id": "synthetic-client-id-123456",
                "client_secret": "synthetic-secret-123456789",
            }
        )
    )
    calls = []

    class Factory:
        def __enter__(self):
            return SimpleNamespace(
                request=SimpleNamespace(
                    new_context=lambda: SimpleNamespace(
                        get=lambda *args, **kwargs: calls.append(args)
                    )
                )
            )

        def __exit__(self, *args):
            pass

    config = Config(service_token_file=token, access_mode="service_token")
    with (
        ServiceTokenPreflight(config, Factory) as session,
        pytest.raises(Refused, match="not a preview-hub environment host"),
    ):
        session.preflight(entry)
    assert calls == []
