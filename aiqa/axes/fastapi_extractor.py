from __future__ import annotations

import ast
import math
import os
import re
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any, cast

from . import Cell

SKIP_DIRS = {"tests", "test", "venv", "env", "node_modules", "build", "dist"}
METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}
AUTH = re.compile(r"auth|permission|role|admin|scope|require|user", re.IGNORECASE)
FLAG = re.compile(r"enable|disable|flag|feature|toggle", re.IGNORECASE)
DEPENDS = {"Depends", "Security"}
FIELDS = {"Field", "Query", "Path", "Body", "Header", "Cookie", "Form"}
LIMITS = {
    "min_length",
    "max_length",
    "ge",
    "gt",
    "le",
    "lt",
    "pattern",
    "regex",
    "multiple_of",
    "max_digits",
    "decimal_places",
    "min_items",
    "max_items",
}
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
    found = re.fullmatch(r"HTTP_(\d{3})_\w+", _name(node))
    if isinstance(value, int):
        return value if _plain(value) else None
    return int(found[1]) if found else None


def _plain(value: Any) -> bool:
    if isinstance(value, int):  # beyond 64 bits is not representable downstream
        return -(2**63) <= value < 2**63
    return isinstance(value, str) or (isinstance(value, float) and math.isfinite(value))


def _deps(*parts: ast.AST) -> list[tuple[ast.expr, ast.Call]]:
    calls = [c for p in parts for c in ast.walk(p) if isinstance(c, ast.Call)]
    found = [
        (c.args[0] if c.args else _kw(c, "dependency"), c)
        for c in calls
        if _name(c) in DEPENDS
    ]
    return [(d, c) for d, c in found if d is not None]


def _ident(key: ast.expr) -> Any:  # only statically equal dict keys collapse
    value = _lit(key)
    try:
        hash(value)
    except TypeError:
        value = None
    if value is not None:
        return ("lit", value)
    named = isinstance(key, ast.Name | ast.Attribute)
    return ("src", ast.unparse(key)) if named else ("id", id(key))


def _strs(node: ast.AST | None) -> list[str] | None:
    value = _lit(node)
    if not isinstance(value, list | tuple | set):
        return None
    return [v for v in cast("Iterable[Any]", value) if isinstance(v, str)]


def _verbs(dec: ast.Call, attr: str) -> list[str]:
    if attr in METHODS:
        return [attr.upper()]
    given = _kw(dec, "methods")  # api_route: FastAPI defaults to GET
    if given is None and any(k.arg is None for k in dec.keywords):
        return []  # **opts may carry the methods
    unset = given is None or (isinstance(given, ast.Constant) and given.value is None)
    return sorted({m.upper() for m in (["GET"] if unset else _strs(given) or [])})


class _Scan(ast.NodeVisitor):
    def __init__(self, rel: str, tree: ast.AST) -> None:
        self.rel, self.cells = rel, list[Cell]()
        self.owners, self.scopes = list[list[tuple[str, str]]](), list[str]()
        self.prefixes, self.gates = dict[str, str | None](), set[int]()
        nodes = list(ast.walk(tree))
        mods = [a.name for n in nodes if isinstance(n, ast.Import) for a in n.names]
        mods += [
            n.module or ""
            for n in nodes
            if isinstance(n, ast.ImportFrom) and not n.level
        ]
        self.fastapi = any(m.split(".")[0] == "fastapi" for m in mods)
        self.imported = {
            a.asname or a.name: a.name
            for n in nodes
            if isinstance(n, ast.ImportFrom)
            for a in n.names
        }

    def add(
        self, node: ast.AST, kind: str, subject: str, ns: str = "", **detail: Any
    ) -> None:
        key = f"{self.rel}::{kind}:{ns}{subject}"
        line = getattr(node, "lineno", 0)
        self.cells.append(Cell(key, AXES[kind], kind, subject, self.rel, line, detail))

    def _bind(self, names: list[str], value: ast.expr, node: ast.stmt) -> None:
        ctor = self.imported.get(_name(value), _name(value))
        if isinstance(value, ast.Call) and ctor in {"APIRouter", "FastAPI"}:
            prefix = _kw(value, "prefix")  # None stays "unresolved" if not a literal
            opts = ctor == "APIRouter" and any(k.arg is None for k in value.keywords)
            if prefix is None and not opts:
                resolved: str | None = ""  # APIRouter(**opts) may carry a prefix
            else:
                resolved = _str(prefix)
            self.prefixes.update({n: resolved for n in names})
        if isinstance(value, ast.Dict) and "transition" in "".join(names).lower():
            table = ".".join([*self.scopes, names[0]])
            last = {_ident(k): (k, e) for k, e in zip(value.keys, value.values) if k}
            for key, ends in last.values():
                many = (
                    ends.elts
                    if isinstance(ends, ast.List | ast.Set | ast.Tuple)
                    else [ends]
                )
                for end in many:
                    src, dst = ast.unparse(key), ast.unparse(end)
                    self.add(node, "transition", f"{table}: {src} -> {dst}")

    def visit_Assign(self, node: ast.Assign) -> None:
        self._bind(
            [t.id for t in node.targets if isinstance(t, ast.Name)], node.value, node
        )
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Name) and node.value:
            self._bind([node.target.id], node.value, node)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        cls = ".".join([*self.scopes, node.name])
        if any(_name(b) in ENUMS for b in node.bases):
            members = [
                t.id
                for s in node.body
                for t in (
                    s.targets
                    if isinstance(s, ast.Assign)
                    else [s.target]
                    if isinstance(s, ast.AnnAssign) and s.value
                    else []
                )
                if isinstance(t, ast.Name) and not t.id.startswith("_")
            ]
            self.add(node, "enum", cls, values=members)
        for s in node.body:
            call = s.value if isinstance(s, ast.AnnAssign) else None
            if (
                isinstance(s, ast.AnnAssign)
                and isinstance(call, ast.Call)
                and _name(call) in FIELDS
            ):
                limits = {
                    k.arg: v
                    for k in call.keywords
                    if k.arg in LIMITS and _plain(v := _lit(k.value))
                }
                if limits:
                    self.add(
                        s, "constraint", f"{cls}.{ast.unparse(s.target)}", **limits
                    )
        self._scoped(node, node.name)

    def _scoped(
        self, node: ast.AST, name: str, owners: list[tuple[str, str]] | None = None
    ) -> None:
        saved = dict(self.prefixes)
        self.scopes.append(name)
        self.owners += [owners] if owners else []
        self.generic_visit(node)
        self.owners = self.owners[: len(self.owners) - bool(owners)]
        self.scopes.pop()
        self.prefixes = saved

    def visit_FunctionDef(self, node: Func) -> None:
        qualified = ".".join([*self.scopes, node.name])
        routes: list[tuple[str, str, ast.Call]] = []
        for dec in node.decorator_list:
            if _name(dec) in VALIDATORS:
                self.add(node, "validator", qualified)
            elif (
                isinstance(dec, ast.Call)
                and isinstance(dec.func, ast.Attribute)
                and dec.func.attr in METHODS | {"api_route"}
            ):
                recv = _name(dec.func.value)
                path = _str(dec.args[0] if dec.args else _kw(dec, "path"))
                if path is not None and recv in self.prefixes:
                    prefix = self.prefixes[recv]
                    note = {} if prefix is not None else {"prefix": "unresolved"}
                    for verb in _verbs(dec, dec.func.attr):
                        route = f"{verb} {prefix or ''}{path}"
                        routes.append((route, f"{recv}:", dec))
                        self.add(node, "route", route, f"{recv}:", **note)
        for route, ns, dec in routes:
            found = dict[str, set[str]]()  # role -> scopes of every Security use
            for dep, call in _deps(dec, node.args):
                if not AUTH.search(_name(dep)):
                    continue
                scopes = _strs(_kw(call, "scopes")) if _name(call) == "Security" else []
                vals = (
                    [*dep.args, *(k.value for k in dep.keywords)]
                    if isinstance(dep, ast.Call)
                    else []
                )
                for role in [s for a in vals if (s := _str(a))] or [_name(dep)]:
                    found.setdefault(role, set()).update(scopes or [])
            for role, scopes in found.items():
                note = {"scopes": sorted(scopes)} if scopes else {}
                self.add(node, "role_check", f"{route} requires {role}", ns, **note)
        owners = [(r, ns) for r, ns, _ in routes] or [(qualified, "")]
        self._scoped(node, node.name, owners)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_If(self, node: ast.If | ast.IfExp) -> None:
        self.gates.update(id(n) for n in ast.walk(node.test))
        self.generic_visit(node)

    visit_IfExp = visit_If

    def visit_Raise(self, node: ast.Raise) -> None:
        exc = node.exc
        if isinstance(exc, ast.Call) and _name(exc) == "HTTPException":
            status = _status(
                _kw(exc, "status_code") or (exc.args[0] if exc.args else None)
            )
            for owner, ns in self.owners[-1] if self.owners else [(self.rel, "")]:
                self.add(node, "error_response", f"{owner} {status}", ns, status=status)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        var = _str(node.args[0] if node.args else _kw(node, "key"))
        env = ast.unparse(node.func) in ENV
        if env and var and (FLAG.search(var) or id(node) in self.gates):
            self.add(node, "feature_flag", var)
        self.generic_visit(node)


def _sources(repo: Path) -> Iterator[Path]:
    for root, dirs, names in os.walk(repo):
        dirs[:] = sorted(
            d for d in dirs if d not in SKIP_DIRS and not d.startswith((".", "__"))
        )
        for name in sorted(names):
            path = Path(root, name)
            skip = name.startswith(("test_", "conftest")) or path.is_symlink()
            if name.endswith(".py") and not skip:
                yield path


class FastApiExtractor:
    """Static `ast` scan only: nothing of the target repo is imported or run."""

    name = "fastapi"

    def extract(self, repo: Path) -> list[Cell] | None:
        found, cells = False, dict[str, Cell]()
        for path in _sources(repo):
            try:
                tree = ast.parse(path.read_bytes())
            except (SyntaxError, ValueError, OSError, RecursionError):
                continue
            scan = _Scan(path.relative_to(repo).as_posix(), tree)
            found = found or scan.fastapi
            try:
                scan.visit(tree)
            except RecursionError:  # a parseable but too deeply nested file
                continue
            for cell in scan.cells:
                cells.setdefault(cell.key, cell)
        ordered = sorted(cells.values(), key=lambda c: (c.file, c.line, c.key))
        return ordered if found else None
