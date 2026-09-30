from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .clock import default_clock
from .contracts import InvalidInput, env_name, load_json, validate
from .run import Run


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(
            fd, "w", encoding="utf-8", errors="backslashreplace", newline="\n"
        ) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def write_json(path: Path, value: object) -> None:
    atomic_write(path, json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def pid_alive(pid: int) -> bool:
    if type(pid) is not int or not 1 <= pid <= 2_147_483_647:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, OverflowError, TypeError, ValueError):
        return False
    except PermissionError:
        return True


RUN_ID = re.compile(r"[a-z][a-z0-9-]{1,30}-[0-9]{8}T[0-9]{6}Z")


class RunStorage:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def create(self, environment: str, at: datetime | None = None) -> Path:
        env_name(environment)
        stamp = (at or default_clock()).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
        path = self.root / f"{environment}-{stamp}"
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            path.mkdir()
        except FileExistsError as exc:
            raise InvalidInput("Run id collision; retry in a new second") from exc
        (path / "scenarios").mkdir()
        return path

    def save(self, run: Run) -> None:
        write_json(self.root / run.id / "run.json", run.as_dict())

    def list(self) -> list[str]:
        return sorted(
            (
                p.parent.name
                for p in self.root.glob("*/run.json")
                if RUN_ID.fullmatch(p.parent.name)
            ),
            key=lambda run_id: (run_id[-16:], run_id),
            reverse=True,
        )

    def load(
        self, run_id: str | None = None, *, check_liveness: bool = False
    ) -> dict[str, Any]:
        ids = self.list()
        if run_id is None:
            if not ids:
                raise InvalidInput("No runs")
            run_id = ids[0]
        if not RUN_ID.fullmatch(run_id):
            raise InvalidInput("Invalid run id")
        try:
            data = validate(
                "run",
                load_json(self.root / run_id / "run.json"),
            )
        except (
            OSError,
            UnicodeDecodeError,
            ValueError,
            RecursionError,
        ) as exc:
            raise InvalidInput("Cannot load run") from exc
        if type(data["pid"]) is not int:
            raise InvalidInput("Invalid run pid")
        if data["state"] in ("CREATED", "PREFLIGHT", "RUNNING") and not (
            check_liveness and data["pid"] != os.getpid() and pid_alive(data["pid"])
        ):
            data["state"] = "INTERRUPTED"
        if data["state"] == "COMPLETED":
            try:
                validate(
                    "qa-report",
                    load_json(self.root / run_id / "report.json"),
                )
            except (OSError, ValueError, RecursionError):
                data["state"] = (
                    "RUNNING"
                    if check_liveness
                    and data["pid"] != os.getpid()
                    and pid_alive(data["pid"])
                    else "INTERRUPTED"
                )
                data["abort_reason"] = (
                    None
                    if data["state"] == "RUNNING"
                    else "COMPLETED without a valid report.json"
                )
        return data


def below_directory(path: Path, directory: Path) -> bool:
    """Reject escapes and links strictly below the trusted directory."""
    try:
        relative = path.relative_to(directory)
        if not relative.parts or ".." in relative.parts:
            return False
        component = directory
        for part in relative.parts:
            component /= part
            if component.is_symlink():
                return False
        return True
    except (ValueError, RuntimeError):
        return False
