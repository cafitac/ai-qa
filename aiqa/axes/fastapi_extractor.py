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
    "length_split": "boundary",
    "feature_flag": "flag",
    "error_response": "empty_error",
}
# Every string `max_length` yields these inputs for the design to cover. The wording states what to send and what to
# observe, never what the code does.
LENGTH_SPLITS = {
    "at_max": "max_length ASCII characters: observe whether it is accepted and what is stored",
    "over_max": "max_length + 1 ASCII characters: observe whether it is accepted and what is stored",
    "multibyte_near_max": (
        "max_length characters of multi-byte text (3-byte Hangul or an astral character): "
        "shows whether the limit counts characters, bytes or UTF-16 units"
    ),
    "normalized_fits": (
        "more than max_length characters whose surplus is leading, trailing or "
        "consecutive whitespace or newlines: shows whether the limit applies "
        "before or after normalizing"
    ),
    "whitespace_preserved": (
        "internal consecutive spaces and newlines within the limit: shows "
        "whether the stored text is exactly the submitted text"
    ),
}
STRINGS = {"str", "StrictStr", "SecretStr", "EmailStr", "Text"}
Func = ast.FunctionDef | ast.AsyncFunctionDef


def _shape(a: ast.expr) -> tuple[bool, list[ast.Call]]:
    """(is a string type, `Field(...)` calls in `Annotated` metadata) of an annotation, looking through quotes, `Optional`,
    `Union`, `| None` and `Annotated`. `list[str]` and other containers are not strings: their `max_length` counts items."""
    if isinstance(a, ast.Constant) and isinstance(a.value, str):
        try:
            return _shape(ast.parse(a.value, mode="eval").body)
        except (SyntaxError, ValueError, RecursionError):
            return False, []
    meta: list[ast.Call] = []
    if isinstance(a, ast.BinOp) and isinstance(a.op, ast.BitOr):
        parts = [a.left, a.right]
    elif isinstance(a, ast.Subscript) and _name(a.value) in {
        "Optional",
        "Annotated",
        "Union",
    }:
        inner = a.slice.elts if isinstance(a.slice, ast.Tuple) else [a.slice]
        parts = inner[:1] if _name(a.value) == "Annotated" else inner
        if _name(a.value) == "Annotated":
            meta = [
                m
                for m in inner[1:]
                if isinstance(m, ast.Call)
                and _name(m) in FIELDS | {"StringConstraints"}
            ]
    else:
        return _name(a) in STRINGS or (
            isinstance(a, ast.Call) and _name(a) == "constr"
        ), []
    real = [
        p
        for p in parts
        if not (isinstance(p, ast.Constant) and p.value in (None, "None"))
    ]
    shapes = [_shape(p) for p in real]
    return bool(real) and all(s for s, _ in shapes), [
        m for _, ms in shapes for m in ms
    ] + meta


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


def _ident(key: ast.expr) -> Any:  # only literal dict keys are known to collapse
    try:
        value = ast.literal_eval(key)
        hash(value)
        return ("lit", value)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return ("id", id(key))


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
            if not isinstance(s, ast.AnnAssign):
                continue
            stringy, calls = _shape(
                s.annotation
            )  # pydantic: Annotated metadata first, the assigned Field() wins
            if isinstance(s.value, ast.Call) and _name(s.value) in FIELDS:
                calls.append(s.value)
            limits: dict[str, Any] = {}
            for call in calls:  # a later non-literal value or None makes the limit unknown, never a stale literal
                for k in call.keywords:
                    if k.arg in LIMITS:
                        if _plain(v := _lit(k.value)):
                            limits[str(k.arg)] = v
                        else:
                            limits.pop(str(k.arg), None)
            if limits:
                field = f"{cls}.{ast.unparse(s.target)}"
                self.add(s, "constraint", field, **limits)
                if (
                    stringy
                    and type(limits.get("max_length")) is int
                    and limits["max_length"] >= 1
                ):
                    for name, text in LENGTH_SPLITS.items():
                        detail = {"max_length": limits["max_length"], "input": text}
                        self.add(s, "length_split", f"{field}#{name}", **detail)
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
