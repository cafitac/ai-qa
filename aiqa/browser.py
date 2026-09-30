from __future__ import annotations

import json
import os
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from types import TracebackType
from typing import Any, Self
from urllib.parse import urlsplit

from .contracts import Config, url_origin
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
        for path in self.temporary_states:
            path.unlink(missing_ok=True)
        self.temporary_states.clear()
        self.current_state = self.config.state_file.expanduser()

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
                state = context.storage_state()
                dashboard_host = urlsplit(self.config.dashboard_url).hostname or ""
                cookies = [
                    cookie
                    for cookie in state["cookies"]
                    if cookie["name"] in ("CF_Authorization", "CF_AppSession")
                    and any(
                        host == cookie["domain"].lstrip(".")
                        or host.endswith("." + cookie["domain"].lstrip("."))
                        for host in (dashboard_host, self.config.access_team_domain)
                    )
                ]
                if not cookies or any(
                    cookie.get("httpOnly") is not True for cookie in cookies
                ):
                    raise Refused(
                        "login_required",
                        "Access cookies must be HttpOnly; session was not saved",
                    )
                save_state(
                    self.config.state_file.expanduser(), state, private_directory=True
                )
            finally:
                browser.close()
        print("session saved")

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
                save_state(path, context.storage_state())
                self.current_state = path
                return path
            finally:
                browser.close()
