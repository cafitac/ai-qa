from __future__ import annotations

import json
import re
import stat
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

from .contracts import Config, InvalidInput, load_json
from .run import Evidence, ScenarioResult
from .secrets import RunSecrets
from .storage import atomic_write, below_directory

PATTERN = re.compile(
    rb"CF_Authorization|CF_AppSession|CF_Binding|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_"
)


class Redactor:
    def __init__(
        self, cookie_values: tuple[str, ...] = (), secret_values: tuple[str, ...] = ()
    ):
        self.cookies = tuple(v.encode() for v in cookie_values if len(v) >= 20) + tuple(
            v.encode() for v in secret_values if v
        )

    @classmethod
    def from_state(
        cls,
        state: Path | None,
        access_team_domain: str = "",
        config: Config | None = None,
        loaded_secrets: RunSecrets | None = None,
    ) -> Redactor:
        secrets = (
            loaded_secrets.values()
            if loaded_secrets is not None
            else (RunSecrets.load(config).values() if config is not None else ())
        )
        if state is None:
            return cls(secret_values=secrets)
        data = load_json(state)
        if not isinstance(data, dict):
            raise InvalidInput("Invalid session state")
        data = cast(dict[str, Any], data)
        return cls(
            tuple(
                cookie["value"]
                for cookie in data.get("cookies", [])
                if cookie.get("name")
                in ("CF_Authorization", "CF_AppSession", "CF_Binding")
                or (
                    access_team_domain
                    and cookie.get("domain", "").lstrip(".") == access_team_domain
                )
            ),
            secret_values=secrets,
        )

    def scan(self, directory: Path) -> bool:
        hit = False
        for path in directory.rglob("*"):
            if not below_directory(path, directory):
                continue
            if not stat.S_ISREG(path.lstat().st_mode):
                continue
            content = path.read_bytes()
            if PATTERN.search(content) or any(
                cookie in content for cookie in self.cookies
            ):
                path.unlink()
                hit = True
        if hit:
            atomic_write(directory / "redacted.log", "redacted\n")
        return hit

    def apply(
        self, result: ScenarioResult, directory: Path, run_dir: Path
    ) -> ScenarioResult:
        # Include parsed verdict text, which may never have appeared in a transcript.
        text = json.dumps({"summary": result.summary, "checks": result.checks}).encode()
        text_hit = bool(PATTERN.search(text) or any(v in text for v in self.cookies))
        hit = self.scan(directory)
        if not hit and not text_hit:
            return result
        atomic_write(directory / "redacted.log", "redacted\n")
        return replace(
            result,
            status="FAILED",
            summary="agent_error",
            reason="agent_error",
            checks=(),
            evidence=(
                Evidence(
                    "log", (directory / "redacted.log").relative_to(run_dir).as_posix()
                ),
            ),
        )
