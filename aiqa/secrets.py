from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import cast

from .contracts import Config, InvalidInput, parse_json

ENV_NAMES = ("AIQA_CF_ACCESS_CLIENT_ID", "AIQA_CF_ACCESS_CLIENT_SECRET")
KEYCHAIN_SERVICE = "aiqa-cf-access"
KEYCHAIN_ACCOUNTS = ("client-id", "client-secret")
KEYCHAIN_ERROR = "Keychain item aiqa-cf-access is unreadable or invalid"


def child_env() -> dict[str, str]:
    return {name: value for name, value in os.environ.items() if name not in ENV_NAMES}


def valid(values: tuple[object, ...]) -> bool:
    return all(
        isinstance(v, str) and len(v) >= 20 and not any(ord(c) < 32 for c in v)
        for v in values
    )


def keychain(account: str, *, read: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", account]
        + (["-w"] if read else []),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE if read else subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        timeout=10,
        check=False,
    )


def access_source(config: Config) -> str | None:
    present = [name in os.environ for name in ENV_NAMES]
    if any(present):
        if not all(present):
            raise InvalidInput(f"Missing {ENV_NAMES[present.index(False)]}")
        return "env"
    try:
        config.service_token_file.stat()
        return "file"
    except FileNotFoundError:
        pass
    except OSError:
        raise InvalidInput("Secret file is unreadable or invalid") from None
    if sys.platform == "darwin" and shutil.which("security"):
        try:
            if keychain(KEYCHAIN_ACCOUNTS[1]).returncode == 0:
                return "keychain"
        except (OSError, subprocess.TimeoutExpired):
            raise InvalidInput(KEYCHAIN_ERROR) from None
    return None


def resolve_access(config: Config, *, descriptor: bool = True) -> Config:
    if config.access_mode != "auto":
        return config
    return replace(
        config,
        access_mode="service_token"
        if descriptor and access_source(config)
        else "session",
    )


def read_secret(path: Path, *, service: bool = False) -> tuple[str, ...]:
    try:
        text = path.read_text(encoding="utf-8").strip()
        if service:
            data = parse_json(text.encode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError
            data = cast(dict[str, object], data)
            values: tuple[object, ...] = (
                data.get("client_id"),
                data.get("client_secret"),
            )
        else:
            values = (text,)
        if not valid(values):
            raise ValueError
        return tuple(str(v) for v in values)
    except (OSError, UnicodeError, ValueError, RecursionError):
        raise InvalidInput("Secret file is unreadable or invalid") from None


@dataclass(frozen=True)
class RunSecrets:
    claude: str | None = field(default=None, repr=False)
    service: tuple[str, ...] = field(default=(), repr=False)

    @classmethod
    def load(cls, config: Config, *, claude: bool = True) -> RunSecrets:
        # Only the files the run actually uses are read and validated.
        def optional(path: Path, service: bool = False) -> tuple[str, ...]:
            try:
                path.stat()
            except FileNotFoundError:
                return ()
            except OSError:
                raise InvalidInput("Secret file is unreadable or invalid") from None
            return read_secret(path, service=service)

        token = optional(config.claude_token_file) if claude else ()
        service: tuple[str, ...] = ()
        if config.access_mode == "service_token":
            source = access_source(config)
            if source == "env":
                service = tuple(os.environ[name] for name in ENV_NAMES)
                if not valid(service):
                    raise InvalidInput("Service token environment is invalid")
            elif source == "file":
                service = read_secret(config.service_token_file, service=True)
            elif source == "keychain":
                try:
                    results = [
                        keychain(account, read=True) for account in KEYCHAIN_ACCOUNTS
                    ]
                    service = tuple(r.stdout.removesuffix("\n") for r in results)
                    if any(r.returncode for r in results) or not valid(service):
                        raise ValueError
                except (OSError, subprocess.TimeoutExpired, ValueError, UnicodeError):
                    raise InvalidInput(KEYCHAIN_ERROR) from None
            else:
                raise InvalidInput("Service token file is required")
        return cls(token[0] if token else None, service)

    def values(self) -> tuple[str, ...]:
        return ((self.claude,) if self.claude else ()) + self.service
