import json
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from playwright.sync_api import Error as PlaywrightError
from test_core import descriptor

from aiqa import mutants
from aiqa.browser import PlaywrightSession, ServiceTokenPreflight
from aiqa.cli import main as cli_main
from aiqa.contracts import Config, EnvironmentDescriptor, InvalidInput, validate
from aiqa.usecases import Refused

NOW = datetime(2040, 1, 15, tzinfo=UTC)
LONG = "aqp-truncate-" + "y" * 40
BASE = {"id": "x-mutant", "service": "backend", "category": "cat", "axis": "axs"}


def post(text, **extra):
    return {
        "method": "POST",
        "path": "/api/notes",
        "json": {"text": text},
        "status": 201,
        **extra,
    }


def mutant(name, ref, *steps):
    check, scenarios = {"steps": list(steps)}, ["frontend/add-note-shows-first"]
    return {
        **BASE,
        "id": name,
        "ref": ref,
        "split": "DEV",
        "scenarios": scenarios,
        "check": check,
    }


LIST = {
    "method": "GET",
    "path": "/api/notes",
    "status": 200,
    "equals": {"0.text": "second"},
}
ORDER = mutant("list-order-asc", "m-order", post("first"), post("second"), LIST)
TRUNCATE = mutant("text-truncated", "m-trunc", post(LONG, equals={"text": LONG}))
CATALOG = {
    "apiVersion": "ai-qa/mutants/v1",
    "project": "demo",
    "mutants": [ORDER, TRUNCATE],
}


class App:
    """The notes API of the example backend with one optional seeded defect."""

    def __init__(self, defect=None):
        self.defect, self.notes = defect, [{"text": "Welcome"}]

    def __call__(self, method, path, body):
        if self.defect in ("down", "missing"):
            return (0, None) if self.defect == "down" else (404, None)
        if method == "POST":
            text = body["text"][:40] if self.defect == "truncate" else body["text"]
            self.notes.insert(0, {"text": text})
            return 201, self.notes[0]
        return 200, self.notes[::-1] if self.defect == "order" else self.notes


def env(name, ref, host, state="READY"):
    d = descriptor(NOW)
    d.update(name=name, state=state)
    d["services"] = [
        {
            **d["services"][0],
            "name": "backend",
            "ref": ref,
            "publicUrl": f"https://{host}",
        }
    ]
    return EnvironmentDescriptor.parse(d)


def http_for(apps):
    return lambda method, url, body: apps[url.split("/")[2]](
        method, "/" + url.split("/", 3)[3], body
    )


def check(entry, baseline=None, defect=None, mutant_ref=None):
    apps = {"base.test": baseline or App(), "mut.test": App(defect)}
    desc = (
        env("mut", mutant_ref or entry["ref"], "mut.test")
        if mutant_ref != "none"
        else None
    )
    return mutants.validate_mutant(
        entry, env("base", "main", "base.test"), desc, "main", http_for(apps), NOW
    )


@pytest.mark.parametrize(
    ("entry", "defect"), [(ORDER, "order"), (TRUNCATE, "truncate")]
)
def test_live_defect_is_validated_with_evidence(entry, defect):
    result = check(entry, defect=defect)
    assert result["validated"] and result["reasons"] == []
    assert (
        result["check_ref"].startswith("http:aaaaaaaaaaaa:step ")
        and result["ref"] == entry["ref"]
    )


def test_defect_that_is_not_live_is_not_validated():
    result = check(ORDER)
    assert (result["validated"], result["check_ref"]) == (False, None)
    assert result["reasons"] == ["defect is not live: the check passes on the mutant"]


def test_check_that_fails_on_the_baseline_is_not_validated():
    result = check(ORDER, baseline=App("order"), defect="order")
    assert result["reasons"] == [
        "baseline does not pass the check: step 3 GET /api/notes: 0.text is 'Welcome', expected 'second'"
    ]


@pytest.mark.parametrize(("defect", "status"), [("down", 0), ("missing", 404)])
def test_unreachable_mutant_is_not_validated(defect, status):
    assert check(ORDER, defect=defect)["reasons"] == [
        f"mutant is not reachable: step 1 POST /api/notes: no answer from the app (HTTP {status})"
    ]


def test_environment_problems_stop_the_check_before_any_request():
    assert check(ORDER, mutant_ref="other")["reasons"] == [
        "mutant: service backend@m-order is not in mut"
    ]
    assert check(ORDER, baseline=App("down"), mutant_ref="none")["reasons"] == [
        "mutant: environment descriptor missing"
    ]
    failed = mutants.validate_mutant(
        ORDER,
        env("base", "main", "base.test", "FAILED"),
        None,
        "main",
        http_for({}),
        NOW,
    )
    assert failed["reasons"][0] == "baseline: environment not ready: state=FAILED"


def run_cli(
    tmp_path,
    monkeypatch,
    apps,
    catalog=CATALOG,
    names=("list-order-asc", "text-truncated"),
):
    def write(name, value):
        text = json.dumps(value) if name.endswith(".json") else yaml.safe_dump(value)
        (tmp_path / name).write_text(text)
        return str(tmp_path / name)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mutants.Config, "load", lambda path=None: Config())
    monkeypatch.setattr(
        mutants, "playwright_http", lambda *_: nullcontext(http_for(apps))
    )
    base = write("b.json", env("base", "main", "base.test").data)
    args = [
        "mutant",
        "validate",
        "--catalog",
        write("c.yaml", catalog),
        "--baseline",
        base,
    ]
    for name, ref in zip(names, ("m-order", "m-trunc"), strict=False):
        path = write(f"{name}.json", env(name[:8], ref, f"{name}.test").data)
        args += ["--mutant", f"{name}={path}"]
    return cli_main(args, clock=lambda: NOW)


def verdicts(capsys):
    return [r["validated"] for r in json.loads(capsys.readouterr().out)["results"]]


def test_cli_prints_results_and_exits_zero_only_when_all_validated(
    tmp_path, monkeypatch, capsys
):
    apps = {
        "base.test": App(),
        "list-order-asc.test": App("order"),
        "text-truncated.test": App("truncate"),
    }
    assert run_cli(tmp_path, monkeypatch, apps) == 0
    assert verdicts(capsys) == [True, True]
    apps["text-truncated.test"] = App()
    assert run_cli(tmp_path, monkeypatch, apps) == 1
    assert verdicts(capsys) == [True, False]


def test_malformed_catalog_or_mutant_argument_is_refused(tmp_path, monkeypatch):
    duplicate = {**CATALOG, "mutants": [ORDER, {**TRUNCATE, "ref": "m-order"}]}
    assert run_cli(tmp_path, monkeypatch, {}, catalog=duplicate) == 2
    assert run_cli(tmp_path, monkeypatch, {}, names=("nope",)) == 2
    binary = {
        **CATALOG,
        "mutants": [mutant("m-bin", "r", {**post("x"), "json": b"\xff"})],
    }
    assert run_cli(tmp_path, monkeypatch, {}, catalog=binary, names=()) == 2
    with pytest.raises(InvalidInput):
        validate("mutant-catalog", {**CATALOG, "mutants": [{**ORDER, "split": "LIVE"}]})


def test_transport_preflights_before_the_request_runtime_and_never_follows_redirects(
    monkeypatch, tmp_path
):
    fetched, preflights, active = [], [], []

    class Context:
        def fetch(self, url, **kwargs):
            fetched.append((url, kwargs))
            status = 302 if url.endswith("/redirect") else 201
            body = (
                b" " * (mutants.MAX_BODY + 1)
                if url.endswith("/big")
                else b'{"ok": true}'
            )
            return SimpleNamespace(
                status=status, body=lambda: body, dispose=lambda: None
            )

    class Factory:
        def __enter__(self):
            assert not active, "a sync Playwright runtime cannot be nested"
            active.append(1)
            new_context = lambda storage_state: Context()
            return SimpleNamespace(request=SimpleNamespace(new_context=new_context))

        def __exit__(self, *args):
            active.clear()

    def preflight(self, url):
        assert not active, "preflight must finish before the request runtime starts"
        preflights.append(url)
        return Path("s.json")

    monkeypatch.setattr(PlaywrightSession, "preflight", preflight)
    origins = {"https://phub-a.cafitac.com", "https://phub-b.cafitac.com"}
    with mutants.playwright_http(Config(), origins, {}, Factory) as http:
        assert http("POST", "https://phub-a.cafitac.com/api/notes", {"text": "x"}) == (
            201,
            {"ok": True},
        )
        assert http("GET", "https://phub-a.cafitac.com/redirect", None)[0] == 302
        assert http("GET", "https://phub-b.cafitac.com/x", None)[0] == 201
        assert http("GET", "https://phub-b.cafitac.com/big", None) == (0, None)
        assert http("GET", "https://other.example/x", None) == (0, None)
    assert preflights == ["https://phub-a.cafitac.com/", "https://phub-b.cafitac.com/"]
    assert all(kwargs["max_redirects"] == 0 for _, kwargs in fetched)


def test_service_token_mode_loads_only_the_access_credentials(monkeypatch, tmp_path):
    token = tmp_path / "token.json"
    token.write_text(json.dumps({"client_id": "i" * 24, "client_secret": "s" * 24}))
    (tmp_path / "broken").write_text(
        "x"
    )  # a broken Claude token must not block Access credentials
    seen = []
    monkeypatch.setattr(
        ServiceTokenPreflight,
        "preflight",
        lambda self, url: seen.append(self.secrets) or Path("s.json"),
    )
    config = Config(
        access_mode="service_token",
        service_token_file=token,
        claude_token_file=tmp_path / "broken",
    )
    factory = lambda: nullcontext(
        SimpleNamespace(request=SimpleNamespace(new_context=lambda storage_state: 1))
    )
    with mutants.playwright_http(config, {"https://phub-a.cafitac.com"}, {}, factory):
        pass
    assert [s.service for s in seen] == [("i" * 24, "s" * 24)]


def test_no_answer_statuses_are_pinned_and_odd_array_indexes_are_missing():
    assert mutants.NO_ANSWER == {0, 301, 302, 303, 307, 308, 401, 403, 404, 405}.union(
        {502, 503, 504, 520, 521, 522, 523, 524, 525, 526, 530}
    )
    assert mutants.dig([1], "\u00b2") is mutants.MISSING
    assert mutants.dig([1], "9" * 5000) is mutants.MISSING
    assert mutants.dig([{"a": 1}], "0.a") == 1


def test_cloudflare_origin_failure_is_no_answer_not_a_live_defect():
    class Origin522(App):
        def __call__(self, method, path, body):
            return (
                (522, None)
                if self.defect == "522"
                else super().__call__(method, path, body)
            )

    result = check(ORDER, defect="order", baseline=None)
    assert result["validated"]
    apps = {"base.test": App(), "mut.test": Origin522("522")}
    result = mutants.validate_mutant(
        ORDER,
        env("base", "main", "base.test"),
        env("mut", "m-order", "mut.test"),
        "main",
        http_for(apps),
        NOW,
    )
    assert result["reasons"][0].startswith(
        "mutant is not reachable: step 1 POST /api/notes: no answer from the app (HTTP 522)"
    )


def test_an_expected_no_answer_status_is_never_a_live_defect():
    gone = mutant(
        "route-gone", "m-gone", {"method": "GET", "path": "/x", "status": 404}
    )
    result = check(gone, baseline=App("missing"), defect="missing")
    assert not result["validated"] and len(result["reasons"]) == 2


def test_json_equality_keeps_booleans_apart_from_numbers():
    assert not mutants.same(1, True) and not mutants.same({"a": [0]}, {"a": [False]})
    assert mutants.same({"a": [True, 1.0]}, {"a": [True, 1]})
    with pytest.raises(InvalidInput):
        validate(
            "mutant-catalog",
            {
                **CATALOG,
                "mutants": [mutant("m-key", "r", {**LIST, "equals": {0: "first"}})],
            },
        )


def test_transport_serializes_json_bodies_and_reports_an_unreachable_origin(
    monkeypatch,
):
    sent, disposed, failures = [], [], {}

    class Context:
        def fetch(self, url, **kwargs):
            sent.append(kwargs)
            return SimpleNamespace(
                status=200, body=lambda: b"1", dispose=lambda: disposed.append(url)
            )

    def preflight(self, url):
        if "phub-b" in url:
            raise PlaywrightError("net::ERR_NAME_NOT_RESOLVED")
        if "phub-c" in url:
            raise Refused("login_required", "Service-token Access exchange refused")
        return Path("s.json")

    factory = lambda: nullcontext(
        SimpleNamespace(
            request=SimpleNamespace(new_context=lambda storage_state: Context())
        )
    )
    monkeypatch.setattr(PlaywrightSession, "preflight", preflight)
    origins = {f"https://phub-{x}.cafitac.com" for x in "abc"}
    with mutants.playwright_http(Config(), origins, failures, factory) as http:
        for body in ("first", None, mutants.MISSING):
            assert http("POST", "https://phub-a.cafitac.com/x", body) == (200, 1)
        assert http("GET", "https://phub-b.cafitac.com/x", None) == (0, None)
        assert http("GET", "https://phub-c.cafitac.com/x", None) == (0, None)
    assert sorted(failures) == [
        "https://phub-b.cafitac.com",
        "https://phub-c.cafitac.com",
    ]
    assert (
        failures["https://phub-c.cafitac.com"]
        == "Service-token Access exchange refused"
    )
    assert len(disposed) == 3
    assert [k.get("data") for k in sent] == ['"first"', "null", None]
    assert (
        sent[0]["headers"] == {"Content-Type": "application/json"}
        and "headers" not in sent[2]
    )
