from __future__ import annotations

import re
import shutil
import subprocess
from collections.abc import Callable
from typing import Any

from .browser import playwright_errors, playwright_factory
from .contracts import PLAYWRIGHT_MCP_PATTERN, Config


def dependency_errors(config: Config, agent: str | None = None) -> list[str]:
    errors: list[str] = []
    if not config.playwright_mcp or not PLAYWRIGHT_MCP_PATTERN.fullmatch(
        config.playwright_mcp
    ):
        errors.append("playwright_mcp must be pinned as @playwright/mcp@x.y.z")
    for name in (agent or config.agent_kind, "npx"):
        if shutil.which(name) is None:
            errors.append(f"{name}: missing from PATH")
    return errors


def doctor(config: Config, factory: Callable[[], Any] = playwright_factory) -> int:
    errors = dependency_errors(config)
    for error in errors:
        print(error)
    missing = bool(errors)
    for name in (config.agent_kind, "npx"):
        path = shutil.which(name)
        if path is None:
            missing = True
            continue
        try:
            result = subprocess.run(
                [path, "--version"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            # Version output is untrusted: report only the numeric version.
            match = re.search(r"\b\d+\.\d+\.\d+\b", result.stdout)
            ok = result.returncode == 0 and match is not None
            print(f"{name}: {match.group() if ok and match else 'version unavailable'}")
            missing |= not ok
        except (OSError, subprocess.TimeoutExpired):
            print(f"{name}: version unavailable")
            missing = True
    if config.agent_kind == "codex":
        print("codex: experimental (unit-tested only)")
    try:
        with factory() as playwright:
            from pathlib import Path

            installed = Path(playwright.chromium.executable_path).is_file()
    except playwright_errors():
        print("Playwright: browser error")
        return 4
    except (ImportError, OSError):
        installed = False
    print(f"Playwright Chromium: {'installed' if installed else 'missing'}")
    state = config.state_file.expanduser()
    present = (
        state.is_file()
        and not state.is_symlink()
        and state.stat().st_mode & 0o777 == 0o600
    )
    print(
        f"session: {'present (0600)' if present else 'missing or unsafe permissions'}"
    )
    return int(missing or not installed or not present)
