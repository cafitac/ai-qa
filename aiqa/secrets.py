from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast

from .contracts import Config, InvalidInput, parse_json


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
        if any(
            not isinstance(v, str) or len(v) < 20 or any(ord(c) < 32 for c in v)
            for v in values
        ):
            raise ValueError
        return tuple(str(v) for v in values)
    except (OSError, UnicodeError, ValueError, RecursionError):
        raise InvalidInput("Secret file is unreadable or invalid") from None


@dataclass(frozen=True)
class RunSecrets:
    claude: str | None = None
    service: tuple[str, ...] = ()

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
            service = optional(config.service_token_file, True)
            if not service:
                raise InvalidInput("Service token file is required")
        return cls(token[0] if token else None, service)

    def values(self) -> tuple[str, ...]:
        return ((self.claude,) if self.claude else ()) + self.service
