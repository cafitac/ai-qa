from __future__ import annotations

import json
import os
import re
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from types import TracebackType
from typing import Any, Self, cast
from urllib.parse import urljoin, urlsplit

from .contracts import Config, InvalidInput, url_origin
from .secrets import RunSecrets
from .storage import atomic_write
from .usecases import Refused


def playwright_factory() -> Any:
    # Lazy import: file/fake workflows and doctor work without Playwright installed.
    from importlib import import_module

    return import_module("playwright.sync_api").sync_playwright()


class BrowserFailure(RuntimeError):
    pass


def playwright_errors() -> tuple[type[Exception], ...]:
    try:
        from playwright.sync_api import Error
    except ImportError:
        return ()
    return (Error,)


def save_state(path: Path, state: Any, *, private_directory: bool = False) -> None:
    if not path.parent.exists():
        path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        if private_directory:
            path.parent.chmod(0o700)
    if private_directory and path.parent.stat().st_mode & 0o022:
        raise Refused(
            "login_required",
            "Session directory is group/world-writable; session was not saved",
        )
    atomic_write(path, json.dumps(state))


def environment_host_pattern(config: Config) -> re.Pattern[str]:
    return re.compile(
        r"phub-[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\."
        + re.escape(config.environment_domain.lower())
    )


def filter_state(
    state: dict[str, Any], config: Config, origins: tuple[str, ...] = ()
) -> dict[str, Any]:
    hosts = {
        (urlsplit(config.dashboard_url).hostname or "").lower(),
        config.access_team_domain.lower(),
    }
    hosts.update(urlsplit(origin).hostname or "" for origin in origins)
    environment_host = environment_host_pattern(config)

    def allowed(host: str) -> bool:
        host = host.lower()
        return host in hosts or environment_host.fullmatch(host) is not None

    return {
        "cookies": [
            cookie
            for cookie in state.get("cookies", [])
            if allowed(cookie.get("domain", "").lstrip("."))
        ],
        "origins": [
            origin
            for origin in state.get("origins", [])
            if allowed(urlsplit(cast(str, origin.get("origin", ""))).hostname or "")
        ],
    }


class PlaywrightSession:
    def __init__(self, config: Config, factory: Callable[[], Any] = playwright_factory):
        self.config = config
        self.factory = factory
        self.temporary_states: list[Path] = []
        self.current_state = config.state_file.expanduser()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        errors: list[OSError] = []
        remaining: list[Path] = []
        for path in self.temporary_states:
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                errors.append(exc)
                remaining.append(path)
        self.temporary_states = remaining
        self.current_state = self.config.state_file.expanduser()
        if errors:
            raise errors[0]

    def login(self) -> None:
        try:
            self._login()
        except playwright_errors() as exc:
            message = (
                "login cancelled"
                if "closed" in str(exc).lower()
                else "login failed: browser error"
            )
            raise BrowserFailure(message) from exc

    def _login(self) -> None:
        with self.factory() as playwright:
            browser = playwright.chromium.launch(headless=False)
            try:
                context = browser.new_context()
                page = context.new_page()
                deadline = time.monotonic() + 600
                page.goto(self.config.dashboard_url, timeout=600_000)
                while url_origin(page.url) != url_origin(self.config.dashboard_url):
                    if time.monotonic() >= deadline:
                        raise Refused("login_required")
                    page.wait_for_timeout(250)
                state = filter_state(context.storage_state(), self.config)
                dashboard_host = urlsplit(self.config.dashboard_url).hostname or ""
                cookies = [
                    cookie
                    for cookie in state["cookies"]
                    if cookie["name"] in ("CF_Authorization", "CF_AppSession")
                    and any(
                        host.lower() == cookie["domain"].lstrip(".").lower()
                        for host in (dashboard_host, self.config.access_team_domain)
                    )
                ]
                if not cookies or any(
                    cookie.get("httpOnly") is not True for cookie in cookies
                ):
                    raise Refused(
                        "login_required",
                        "Exact-host Access cookies for the dashboard or team domain must be HttpOnly; session was not saved",
                    )
                save_state(
                    self.config.state_file.expanduser(), state, private_directory=True
                )
            finally:
                browser.close()
        print(f"session saved ({len(state['cookies'])} Access cookies)")

    def preflight(self, url: str) -> Path:
        if (
            not self.current_state.is_file()
            or self.current_state.stat().st_mode & 0o777 != 0o600
        ):
            raise Refused("login_required", "Run aiqa login")
        with self.factory() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = browser.new_context(storage_state=str(self.current_state))
                page = context.new_page()
                page.goto(url, timeout=60_000)
                if url_origin(page.url) != url_origin(url):
                    raise Refused("login_required", "Run aiqa login")
                fd, name = tempfile.mkstemp(prefix="aiqa-state-", suffix=".json")
                os.close(fd)
                path = Path(name)
                self.temporary_states.append(path)
                save_state(path, filter_state(context.storage_state(), self.config))
                self.current_state = path
                return path
            finally:
                browser.close()


class ServiceTokenPreflight(PlaywrightSession):
    """Exchange service credentials for cookies without forwarding headers."""

    def __init__(self, config: Config, factory: Callable[[], Any] = playwright_factory):
        super().__init__(config, factory)
        self.origins: tuple[str, ...] = ()
        self.secrets: RunSecrets | None = None

    def preflight(self, url: str) -> Path:
        try:
            secrets = (
                self.secrets
                if self.secrets is not None
                else RunSecrets.load(self.config)
            )
            if not secrets.service:
                raise InvalidInput("Service token file is required")
            token = dict(
                zip(("client_id", "client_secret"), secrets.service, strict=True)
            )
        except InvalidInput:
            raise Refused(
                "login_required", "Service token file is missing or invalid"
            ) from None
        entry_origin = url_origin(url).lower()
        if not entry_origin.startswith("https://"):
            raise Refused("login_required", "Service-token entry origin requires HTTPS")
        # Credentials go only to a preview-hub environment host on the default port.
        entry_host = entry_origin.removeprefix("https://")
        if not environment_host_pattern(self.config).fullmatch(entry_host):
            raise Refused(
                "login_required",
                "Service-token entry origin is not a preview-hub environment host",
            )
        headers = {
            "CF-Access-Client-Id": token["client_id"],
            "CF-Access-Client-Secret": token["client_secret"],
        }
        with self.factory() as playwright:
            context = playwright.request.new_context()
            try:
                current = url
                for attempt in range(11):
                    response = context.get(
                        current,
                        headers=headers if attempt == 0 else {},
                        max_redirects=0,
                        timeout=60_000,
                    )
                    status = response.status
                    location = response.headers.get("location")
                    response.dispose()
                    if status not in (301, 302, 303, 307, 308):
                        if status >= 400 or url_origin(current).lower() != entry_origin:
                            raise Refused(
                                "login_required",
                                "Service-token Access exchange refused",
                            )
                        break
                    if not location or attempt == 10:
                        raise Refused(
                            "login_required", "Service-token redirect limit exceeded"
                        )
                    current = urljoin(current, location)
                    if url_origin(current).lower() not in (
                        entry_origin,
                        f"https://{self.config.access_team_domain}".lower(),
                    ):
                        raise Refused(
                            "login_required",
                            "Service-token redirect outside allowed origins",
                        )
                state = filter_state(context.storage_state(), self.config, self.origins)
                state = {
                    "cookies": [
                        c
                        for c in state["cookies"]
                        if c.get("name")
                        in ("CF_Authorization", "CF_AppSession", "CF_Binding")
                    ],
                    "origins": [],
                }
                host = (urlsplit(url).hostname or "").lower()
                if not any(
                    c.get("name") == "CF_Authorization"
                    and c.get("domain", "").lstrip(".").lower() == host
                    and c.get("httpOnly") is True
                    for c in state["cookies"]
                ):
                    raise Refused(
                        "login_required", "Exact-host Access cookies must be HttpOnly"
                    )
                state["cookies"] = [
                    c for c in state["cookies"] if c.get("httpOnly") is True
                ]
                fd, name = tempfile.mkstemp(prefix="aiqa-state-", suffix=".json")
                os.close(fd)
                path = Path(name)
                self.temporary_states.append(path)
                save_state(path, state)
                self.current_state = path
                return path
            finally:
                context.dispose()
