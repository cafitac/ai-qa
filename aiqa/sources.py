from __future__ import annotations

import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any
from urllib.parse import quote, urljoin, urlsplit

from .browser import PlaywrightSession
from .contracts import (
    EnvironmentDescriptor,
    InvalidInput,
    Scenario,
    env_name,
    parse_json,
    parse_scenarios,
    parse_yaml,
    url_origin,
)
from .usecases import Refused


class HubDescriptorSource:
    def __init__(self, session: PlaywrightSession):
        self.session = session

    def get(self, environment: str) -> EnvironmentDescriptor:
        env_name(environment)
        config = self.session.config
        with self.session.factory() as playwright:
            context = playwright.request.new_context(
                storage_state=str(self.session.current_state)
            )
            try:
                response = context.get(
                    f"{config.dashboard_url.rstrip('/')}/api/environments/{quote(environment)}?format=descriptor",
                    timeout=30_000,
                    max_redirects=0,
                )
                if (
                    response.status in (401, 403)
                    or 300 <= response.status < 400
                    or url_origin(response.url) != url_origin(config.dashboard_url)
                ):
                    raise Refused("login_required", "Run aiqa login")
                if response.status == 404:
                    raise Refused(
                        "environment_not_ready",
                        "Environment descriptor is not available",
                    )
                if response.status != 200:
                    raise OSError("Descriptor request failed")
                return EnvironmentDescriptor.parse(parse_json(response.body()))
            finally:
                context.dispose()


class RawRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        # Redirects are followed explicitly with the policy of the current request.
        return None


class GitHubRawScenarioSource:
    def __init__(self, opener: Callable[..., Any] | None = None):
        self.notes: list[str] = []
        self.opener = opener or urllib.request.build_opener(RawRedirectHandler()).open

    def request(self, url: str, host: str, timeout: int) -> Any:
        response: Any
        for hop in range(4):
            try:
                response = self.opener(url, timeout=timeout)
            except urllib.error.HTTPError as exc:
                response = exc
            try:
                self.check_url(response.geturl(), host)
                if response.status not in (301, 302, 303, 307, 308):
                    return response
                location = response.headers.get("Location")
                if not location:
                    raise OSError("GitHub redirect has no target")
                target = urljoin(url, location)
                self.check_url(target, host)
                if hop == 3:
                    raise OSError("GitHub redirect limit exceeded")
                url = target
            except BaseException:
                response.close()
                raise
            response.close()
        raise AssertionError("Unreachable redirect state")

    @staticmethod
    def check_url(url: str, host: str) -> None:
        try:
            parsed = urlsplit(url)
            allowed = (
                parsed.scheme == "https"
                and parsed.hostname == host
                and parsed.port in (None, 443)
                and parsed.username is None
                and parsed.password is None
            )
        except ValueError:
            allowed = False
        if not allowed:
            raise OSError("GitHub redirect outside request host")

    def missing_file(self, service: str, repo: str, commit: str) -> list[Scenario]:
        url = f"https://api.github.com/repos/{quote(repo, safe='/')}/commits/{quote(commit, safe='')}"
        # No credentials or auth headers: visibility must be public.
        with self.request(url, "api.github.com", 10) as response:
            self.check_visibility(response.status, response.headers)
        self.notes.append(f"{service}: no scenario file")
        return []

    @staticmethod
    def check_visibility(status: int, headers: Any) -> None:
        if status == 404:
            raise Refused(
                "invalid_scenarios",
                "Repository is not publicly readable at the requested commit",
            )
        if status in (403, 429) and (
            headers.get("X-RateLimit-Remaining") == "0"
            or headers.get("Retry-After") is not None
        ):
            raise Refused("source_unavailable", "GitHub rate limit; retry later")
        if status != 200:
            raise OSError("Commit visibility request failed")

    def load(
        self, service: str, repo: str, commit: str, timeout_cap: int
    ) -> list[Scenario]:
        # Repo and commit have already passed the descriptor schema; quote defensively.
        repo = (
            repo.removeprefix("https://github.com/")
            .removeprefix("github.com/")
            .removesuffix(".git")
        )
        url = f"https://raw.githubusercontent.com/{quote(repo, safe='/')}/{quote(commit, safe='')}/qa/scenarios.yaml"
        with self.request(url, "raw.githubusercontent.com", 30) as response:
            if response.status == 404:
                return self.missing_file(service, repo, commit)
            if response.status != 200:
                raise OSError("Scenario request failed")
            content = response.read(256 * 1024 + 1)
        if len(content) > 256 * 1024:
            raise InvalidInput("Scenario file exceeds 256 KiB")
        return parse_scenarios(parse_yaml(content), service, timeout_cap)
