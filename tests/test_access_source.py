import json
import subprocess
from dataclasses import replace
from types import SimpleNamespace

import pytest

from aiqa.browser import ServiceTokenPreflight
from aiqa.cli import main
from aiqa.contracts import Config, InvalidInput
from aiqa.secrets import ENV_NAMES, RunSecrets, access_source, resolve_access
from aiqa.usecases import Refused


@pytest.mark.parametrize("source", ["env", "file", "keychain"])
def test_sources_and_leak_boundaries(tmp_path, monkeypatch, capsys, source):
    values = ("distinctive-client-identifier-123", "distinctive-access-secret-456")
    config = Config(
        service_token_file=tmp_path / "token",
        access_mode="auto",
        access_team_domain="team.example",
    )
    calls = []
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("aiqa.secrets.sys.platform", "darwin")
    monkeypatch.setattr("aiqa.secrets.shutil.which", lambda name: None)

    def execute(argv, **kwargs):
        calls.append((argv, kwargs))
        if "--version" in argv:
            return SimpleNamespace(returncode=0, stdout="1.2.3")
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert kwargs["stderr"] == subprocess.DEVNULL
        assert kwargs["timeout"] == 10 and kwargs["check"] is False
        if "-w" not in argv:
            assert kwargs["stdout"] == subprocess.DEVNULL
        return SimpleNamespace(
            returncode=0, stdout=values[argv[-2] == "client-secret"] + "\n"
        )

    monkeypatch.setattr("aiqa.secrets.subprocess.run", execute)
    if source == "env":
        for name, value in zip(ENV_NAMES, values, strict=True):
            monkeypatch.setenv(name, value)
    elif source == "file":
        config.service_token_file.write_text(
            json.dumps(dict(zip(("client_id", "client_secret"), values, strict=True)))
        )
    else:
        monkeypatch.setattr(
            "aiqa.secrets.shutil.which",
            lambda name: "/mock/security" if name == "security" else None,
        )
    assert access_source(config) == source
    resolved = resolve_access(config)
    assert resolved.access_mode == "service_token"
    assert (
        resolve_access(replace(config, access_mode="session")).access_mode == "session"
    )
    secrets = RunSecrets.load(resolved, claude=False)
    assert secrets.values() == values
    monkeypatch.setattr(Config, "load", lambda path: config)
    monkeypatch.setattr("aiqa.doctor.dependency_errors", lambda config: [])
    monkeypatch.setattr("aiqa.doctor.playwright_factory", lambda: None)
    # Supply a fake installed Chromium through the default factory binding.
    import aiqa.doctor as doctor_module

    original = doctor_module.doctor
    executable = tmp_path / "chromium"
    executable.touch()

    class Factory:
        def __enter__(self):
            return SimpleNamespace(
                chromium=SimpleNamespace(executable_path=str(executable)),
                request=SimpleNamespace(new_context=lambda: self),
            )

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(
        doctor_module, "doctor", lambda config: original(config, Factory)
    )
    main(["doctor", "--access", "service-token"])
    captured = capsys.readouterr()
    assert f"access: service token ({source})" in captured.out
    for value in values:
        assert value not in repr(secrets)
        assert value not in str(calls)
        assert value not in str(captured)
    for argv, kwargs in calls:
        assert argv == [
            "security",
            "find-generic-password",
            "-s",
            "aiqa-cf-access",
            "-a",
            argv[5],
            *(["-w"] if "-w" in argv else []),
        ]
        assert argv[5] in ("client-id", "client-secret")
        assert kwargs["stdout"] == (
            subprocess.PIPE if "-w" in argv else subprocess.DEVNULL
        )
    if source == "keychain":
        assert any("-w" in argv for argv, _ in calls)
        assert any("-w" not in argv for argv, _ in calls)
    if source == "env":
        monkeypatch.delenv(ENV_NAMES[1])
    elif source == "file":
        config.service_token_file.write_text("{}")
    else:
        monkeypatch.setattr(
            "aiqa.secrets.subprocess.run",
            lambda *a, **kw: (_ for _ in ()).throw(OSError(values[1])),
        )
    with pytest.raises(InvalidInput) as error:
        RunSecrets.load(resolved, claude=False)
    assert all(v not in str(error.value) + repr(error.value) for v in values)


def test_absent_and_partial_environment(tmp_path, monkeypatch, capsys):
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("aiqa.secrets.shutil.which", lambda name: None)
    config = Config(service_token_file=tmp_path / "absent", access_mode="auto")
    assert resolve_access(config).access_mode == "session"
    monkeypatch.setenv(ENV_NAMES[0], "distinctive-client-identifier-123")
    monkeypatch.setattr(Config, "load", lambda path: config)
    assert main(["doctor"]) == 2
    assert ENV_NAMES[1] in capsys.readouterr().out


@pytest.mark.parametrize("failure", ["rc", "timeout", "invalid"])
def test_unreadable_keychain(tmp_path, monkeypatch, failure):
    from aiqa.secrets import KEYCHAIN_ERROR

    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("aiqa.secrets.sys.platform", "darwin")
    monkeypatch.setattr("aiqa.secrets.shutil.which", lambda name: "/mock/security")

    def execute(argv, **kwargs):
        if "-w" not in argv:
            return SimpleNamespace(returncode=0)
        if failure == "timeout":
            raise subprocess.TimeoutExpired(argv, 10)
        return SimpleNamespace(returncode=1 if failure == "rc" else 0, stdout="invalid")

    monkeypatch.setattr("aiqa.secrets.subprocess.run", execute)
    config = Config(service_token_file=tmp_path / "absent", access_mode="service_token")
    with pytest.raises(InvalidInput, match=f"^{KEYCHAIN_ERROR}$"):
        RunSecrets.load(config, claude=False)


@pytest.mark.parametrize(
    "descriptor,partial", [(False, False), (True, False), (False, True)]
)
def test_auto_token_without_descriptor_keeps_session(
    tmp_path, monkeypatch, descriptor, partial
):
    from aiqa.browser import PlaywrightSession

    monkeypatch.setenv(ENV_NAMES[0], "distinctive-client-identifier-123")
    if not partial:
        monkeypatch.setenv(ENV_NAMES[1], "distinctive-access-secret-456")
    config = Config(service_token_file=tmp_path / "absent", access_mode="auto")
    monkeypatch.setattr(Config, "load", lambda path: config)
    if not descriptor:

        def unexpected_probe(config):
            raise AssertionError("Session-only run must not probe token sources")

        monkeypatch.setattr("aiqa.secrets.access_source", unexpected_probe)
    monkeypatch.setattr("aiqa.doctor.dependency_errors", lambda config, agent: [])
    seen = []

    class Usecase:
        last_run = None

        def __init__(self, *args, browser_session, **kwargs):
            seen.append((args[3].access_mode, type(browser_session)))

        def execute(self, *args):
            return 0

    monkeypatch.setattr("aiqa.cli.RunScenarios", Usecase)
    argv = ["run", "demo", "--agent", "claude"]
    if descriptor:
        argv += ["--descriptor", str(tmp_path / "descriptor.json")]
    assert main(argv) == 0
    assert seen[0][0] == ("service_token" if descriptor else "session")
    assert (seen[0][1] is ServiceTokenPreflight) == descriptor
    assert descriptor or seen[0][1] is PlaywrightSession


@pytest.mark.parametrize(
    "status,cookie,location,expected",
    [
        (401, False, None, "rejected the service token"),
        (403, True, None, "origin refused it"),
        (302, False, "https://team.example/login", "rejected the service token"),
        (302, False, "https://TEAM.EXAMPLE/login", "rejected the service token"),
    ],
)
def test_preflight_outcomes(status, cookie, location, expected):
    class Request:
        def get(self, *args, **kwargs):
            return SimpleNamespace(
                status=status,
                headers={"location": location} if location else {},
                dispose=lambda: None,
            )

        def storage_state(self):
            return {
                "cookies": [
                    {"name": "CF_Authorization", "domain": "phub-demo.cafitac.com"}
                ]
                if cookie
                else []
            }

        def dispose(self):
            pass

    class Factory:
        def __enter__(self):
            return SimpleNamespace(request=SimpleNamespace(new_context=Request))

        def __exit__(self, *args):
            pass

    config = Config(access_mode="service_token", access_team_domain="team.example")
    with ServiceTokenPreflight(config, Factory) as session:
        session.secrets = RunSecrets(
            service=("synthetic-client-id-12345", "synthetic-client-secret-12345")
        )
        with pytest.raises(Refused, match=expected):
            session.preflight("https://phub-demo.cafitac.com/")


@pytest.mark.parametrize("operation", ["get", "storage_state"])
def test_preflight_transport_error_is_sanitized(monkeypatch, operation):
    secret = "synthetic-transport-secret-12345"
    disposed = []

    class TransportError(Exception):
        pass

    class Request:
        def get(self, *args, **kwargs):
            if operation == "get":
                raise TransportError(secret)
            return SimpleNamespace(status=403, headers={}, dispose=lambda: None)

        def storage_state(self):
            raise TransportError(secret)

        def dispose(self):
            disposed.append(True)

    class Factory:
        def __enter__(self):
            return SimpleNamespace(request=SimpleNamespace(new_context=Request))

        def __exit__(self, *args):
            pass

    monkeypatch.setattr("aiqa.browser.playwright_errors", lambda: (TransportError,))
    with ServiceTokenPreflight(Config(access_mode="service_token"), Factory) as session:
        session.secrets = RunSecrets(service=("synthetic-client-id-12345", secret))
        with pytest.raises(Refused) as error:
            session.preflight("https://phub-demo.cafitac.com/")
    assert str(error.value) == "Service-token Access request failed"
    assert secret not in str(error.value) + repr(error.value)
    assert error.value.__cause__ is None
    assert error.value.__suppress_context__ is True
    assert disposed == [True]
