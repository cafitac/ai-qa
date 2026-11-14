from __future__ import annotations

import ast
import os
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from . import Cell

SKIP_DIRS = {"tests", "test", "venv", "env", "node_modules", "build", "dist"}
MAX_BYTES = 1_000_000
METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}
AUTH = re.compile(r"auth|permission|role|admin|scope|require|user", re.IGNORECASE)
FLAG = re.compile(r"enable|disable|flag|feature|toggle", re.IGNORECASE)
LIMITS = {"min_length", "max_length", "ge", "gt", "le", "lt", "pattern"}
VALIDATORS = {"field_validator", "validator", "model_validator", "root_validator"}
ENUMS = {"Enum", "StrEnum", "IntEnum", "Flag", "IntFlag"}
ENV = {"os.getenv", "getenv", "os.environ.get", "environ.get"}
AXES = {
    "route": "flow",
    "role_check": "permission",
    "enum": "state",
    "transition": "state",
    "validator": "validation",
    "constraint": "validation",
    "feature_flag": "flag",
    "error_response": "empty_error",
}
Func = ast.FunctionDef | ast.AsyncFunctionDef


def _name(node: ast.AST | None) -> str:
    if isinstance(node, ast.Call):
        return _name(node.func)
    if isinstance(node, ast.Attribute):
        return node.attr
    return node.id if isinstance(node, ast.Name) else ""


def _lit(node: ast.AST | None) -> Any:
    try:
        return None if node is None else ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return None


def _str(node: ast.AST | None) -> str | None:
    value = _lit(node)
    return value if isinstance(value, str) else None


def _kw(call: ast.Call, name: str) -> ast.expr | None:
    return next((k.value for k in call.keywords if k.arg == name), None)


def _status(node: ast.AST | None) -> int | None:
    value = _lit(node)
    found = re.search(r"HTTP_(\d{3})", ast.unparse(node)) if node else None
    return value if isinstance(value, int) else int(found[1]) if found else None


class _Scan(ast.NodeVisitor):
    def __init__(self, rel: str) -> None:
        self.rel, self.cells = rel, list[Cell]()
        self.owners, self.scopes = list[str](), list[str]()
        self.prefixes, self.gates = dict[str, str](), set[int]()

    def add(self, node: ast.AST, kind: str, subject: str, **detail: Any) -> None:
        key = f"{self.rel}::{kind}:{subject}"
        self.cells.append(
            Cell(
                key,
                AXES[kind],
                kind,
                subject,
                self.rel,
                getattr(node, "lineno", 0),
                detail,
            )
        )

    def visit_Assign(self, node: ast.Assign) -> None:
        names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        value = node.value
        if isinstance(value, ast.Call) and _name(value) in {"APIRouter", "FastAPI"}:
            self.prefixes.update({n: _str(_kw(value, "prefix")) or "" for n in names})
        if isinstance(value, ast.Dict) and any(
            "transition" in n.lower() for n in names
        ):
            for key, ends in zip(value.keys, value.values):
                many = (
                    ends.elts
                    if isinstance(ends, ast.List | ast.Set | ast.Tuple)
                    else [ends]
                )
                if key is None:
                    continue
                for end in many:
                    src, dst = (_name(x) or ast.unparse(x) for x in (key, end))
                    self.add(node, "transition", f"{names[0]}: {src} -> {dst}")
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if any(_name(b) in ENUMS for b in node.bases):
            members = [
                t.id
                for s in node.body
                if isinstance(s, ast.Assign)
                for t in s.targets
                if isinstance(t, ast.Name)
            ]
            self.add(node, "enum", node.name, values=members)
        for s in node.body:
            call = s.value if isinstance(s, ast.AnnAssign) else None
            limits = (
                {k.arg: _lit(k.value) for k in call.keywords if k.arg in LIMITS}
                if isinstance(call, ast.Call)
                else {}
            )
            if limits and isinstance(s, ast.AnnAssign):
                self.add(
                    s,
                    "constraint",
                    f"{node.name}.{ast.unparse(s.target)}",
                    **limits,
                )
        self.scopes.append(node.name)
        self.generic_visit(node)
        self.scopes.pop()

    def visit_FunctionDef(self, node: Func) -> None:
        qualified = ".".join([*self.scopes, node.name])
        route = None
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            if _name(dec) in VALIDATORS:
                self.add(node, "validator", qualified)
            elif (
                isinstance(dec.func, ast.Attribute)
                and dec.func.attr in METHODS
                and dec.args
                and (path := _str(dec.args[0])) is not None
            ):
                prefix = self.prefixes.get(_name(dec.func.value), "")
                route = f"{dec.func.attr.upper()} {prefix}{path}"
                self.add(node, "route", route)
        if route:
            for call in (
                c for p in [*node.decorator_list, node.args] for c in ast.walk(p)
            ):
                dep = (
                    call.args[0]
                    if isinstance(call, ast.Call)
                    and _name(call) in {"Depends", "Security"}
                    and call.args
                    else None
                )
                if dep and AUTH.search(_name(dep)):
                    roles = [s for a in getattr(dep, "args", []) if (s := _str(a))]
                    for role in roles or [_name(dep)]:
                        self.add(node, "role_check", f"{route} requires {role}")
        self.owners.append(route or qualified)
        self.scopes.append(node.name)
        self.generic_visit(node)
        self.scopes.pop()
        self.owners.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_If(self, node: ast.If) -> None:
        self.gates.add(
            id(node.test.value if isinstance(node.test, ast.NamedExpr) else node.test)
        )
        self.generic_visit(node)

    def visit_Raise(self, node: ast.Raise) -> None:
        exc = node.exc
        if isinstance(exc, ast.Call) and _name(exc) == "HTTPException":
            status = _status(
                _kw(exc, "status_code") or (exc.args[0] if exc.args else None)
            )
            owner = self.owners[-1] if self.owners else self.rel
            self.add(node, "error_response", f"{owner} {status}", status=status)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        var = _str(node.args[0]) if node.args else None
        if (
            ast.unparse(node.func) in ENV
            and var
            and (FLAG.search(var) or id(node) in self.gates)
        ):
            self.add(node, "feature_flag", var)
        self.generic_visit(node)


def _sources(repo: Path) -> Iterator[Path]:
    for root, dirs, names in os.walk(repo):
        dirs[:] = sorted(
            d for d in dirs if d not in SKIP_DIRS and not d.startswith((".", "__"))
        )
        for name in sorted(names):
            path = Path(root, name)
            if (
                name.endswith(".py")
                and not name.startswith("test_")
                and name != "conftest.py"
                and not path.is_symlink()
            ):
                yield path


def _imports_fastapi(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        mods = (
            [a.name for a in node.names]
            if isinstance(node, ast.Import)
            else [node.module or ""]
            if isinstance(node, ast.ImportFrom) and not node.level
            else []
        )
        if any(m == "fastapi" or m.startswith("fastapi.") for m in mods):
            return True
    return False


class FastApiExtractor:
    """Static `ast` scan only: nothing of the target repo is imported or run."""

    name = "fastapi"

    def extract(self, repo: Path) -> list[Cell] | None:
        found, cells = False, dict[str, Cell]()
        for path in _sources(repo):
            try:
                if path.stat().st_size > MAX_BYTES:
                    continue
                tree = ast.parse(path.read_bytes())
            except (SyntaxError, ValueError, OSError, RecursionError):
                continue
            found = found or _imports_fastapi(tree)
            scan = _Scan(path.relative_to(repo).as_posix())
            scan.visit(tree)
            for cell in scan.cells:
                cells.setdefault(cell.key, cell)
        return (
            sorted(cells.values(), key=lambda c: (c.file, c.line, c.key))
            if found
            else None
        )
