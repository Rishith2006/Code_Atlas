"""AST-based Python project parser.

Walks a directory of ``.py`` files and extracts a structural model:
modules, functions (incl. methods), classes, imports and raw call sites.
Everything is stdlib-only so analysis works offline.
"""
from __future__ import annotations

import ast
import os
from dataclasses import dataclass, field


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #

@dataclass
class ImportInfo:
    module: str            # e.g. "os.path" for `import os.path`, "math" for `from math import sqrt`
    names: list            # imported names for from-imports, else []
    lineno: int
    is_from: bool
    level: int             # relative-import level (0 = absolute)


@dataclass
class FunctionInfo:
    name: str
    qualified_name: str    # module[.Class].func
    file: str              # path relative to project root
    lineno: int
    end_lineno: int
    args: list             # e.g. ["x", "y=2", "*args", "**kw"]
    docstring: str
    source: str
    calls: list            # raw dotted names called, e.g. ["len", "self.save", "os.path.join"]
    decorators: list
    is_method: bool
    class_name: str | None
    complexity: int = 1
    loc: int = 0
    max_nesting: int = 0
    risk_score: float = 0.0
    risk_level: str = "Low"
    suggestions: list = field(default_factory=list)


@dataclass
class ClassInfo:
    name: str
    qualified_name: str
    file: str
    lineno: int
    end_lineno: int
    bases: list
    docstring: str
    methods: list          # qualified names of methods


@dataclass
class ModuleInfo:
    path: str              # relative path, e.g. "pkg/utils.py"
    dotted_name: str       # e.g. "pkg.utils"
    docstring: str
    imports: list          # ImportInfo
    functions: list        # FunctionInfo (includes methods)
    classes: list          # ClassInfo
    loc: int


@dataclass
class Project:
    name: str
    root: str
    modules: list = field(default_factory=list)

    def all_functions(self) -> list:
        out = []
        for m in self.modules:
            out.extend(m.functions)
        return out

    def find_function(self, name: str):
        """Find by qualified name, short name, or unique substring (case-insensitive)."""
        name = name.strip()
        funcs = self.all_functions()
        for f in funcs:                       # exact qualified / short match first
            if f.qualified_name == name or f.name == name:
                return f
        lowered = name.lower()
        cands = [f for f in funcs
                 if lowered in f.qualified_name.lower() or lowered in f.name.lower()]
        if len(cands) == 1:
            return cands[0]
        # prefer exact short-name match among candidates
        for f in cands:
            if f.name.lower() == lowered:
                return f
        return cands[0] if cands else None

    def search_functions(self, query: str, limit: int = 20) -> list:
        q = query.lower().strip()
        if not q:
            return []
        scored = []
        for f in self.all_functions():
            score = 0
            if f.name.lower() == q:
                score = 100
            elif q in f.qualified_name.lower():
                score = 60
            elif q in (f.docstring or "").lower():
                score = 30
            elif q in f.source.lower():
                score = 10
            if score:
                scored.append((score, f))
        scored.sort(key=lambda t: (-t[0], t[1].qualified_name))
        return [f for _, f in scored[:limit]]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _call_name(func: ast.AST) -> str:
    """Best-effort dotted name for a call's func expression."""
    parts = []
    node = func
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    if isinstance(node, ast.Call):
        return "<call-result>"
    if isinstance(node, ast.Subscript):
        return _call_name(node.value) + "[...]"
    return "<expr>"


class _CallCollector(ast.NodeVisitor):
    def __init__(self):
        self.calls: list[str] = []

    def visit_Call(self, node: ast.Call):
        self.calls.append(_call_name(node.func))
        self.generic_visit(node)


def _format_args(node: ast.arguments) -> list:
    out = []
    defaults = [None] * (len(node.args) - len(node.defaults)) + list(node.defaults)
    for a, d in zip(node.args, defaults):
        out.append(a.arg if d is None else f"{a.arg}=...")
    if node.vararg:
        out.append("*" + node.vararg.arg)
    for a, d in zip(node.kwonlyargs, node.kw_defaults):
        out.append(a.arg if d is None else f"{a.arg}=...")
    if node.kwarg:
        out.append("**" + node.kwarg.arg)
    return out


def _decorator_name(d: ast.AST) -> str:
    if isinstance(d, ast.Name):
        return d.id
    if isinstance(d, ast.Attribute):
        return _call_name(d)
    if isinstance(d, ast.Call):
        return _call_name(d.func) + "(...)"
    return "<decorator>"


# --------------------------------------------------------------------------- #
# Module parsing
# --------------------------------------------------------------------------- #

class _ModuleVisitor(ast.NodeVisitor):
    def __init__(self, module: ModuleInfo, source: str):
        self.module = module
        self.source = source
        self.class_stack: list[str] = []
        self.func_stack: list[str] = []

    # -- imports ---------------------------------------------------------- #
    def visit_Import(self, node: ast.Import):
        for a in node.names:
            self.module.imports.append(ImportInfo(
                module=a.name, names=[], lineno=node.lineno,
                is_from=False, level=0))
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        self.module.imports.append(ImportInfo(
            module=node.module or "", names=[a.name for a in node.names],
            lineno=node.lineno, is_from=True, level=node.level or 0))
        self.generic_visit(node)

    # -- classes ----------------------------------------------------------- #
    def visit_ClassDef(self, node: ast.ClassDef):
        qname = f"{self.module.dotted_name}." + ".".join(self.class_stack + [node.name])
        bases = []
        for b in node.bases:
            bases.append(_call_name(b) if not isinstance(b, ast.Name) else b.id)
        cls = ClassInfo(
            name=node.name, qualified_name=qname, file=self.module.path,
            lineno=node.lineno, end_lineno=node.end_lineno or node.lineno,
            bases=bases, docstring=ast.get_docstring(node) or "", methods=[])
        self.module.classes.append(cls)
        self.class_stack.append(node.name)
        # visit body manually so methods get recorded on this class
        for stmt in node.body:
            self.visit(stmt)
        self.class_stack.pop()

    # -- functions ---------------------------------------------------------- #
    def _record_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef):
        cls = self.class_stack[-1] if self.class_stack else None
        prefix = ".".join(self.func_stack + ([cls] if cls and not self.func_stack else []))
        # qualified name: module[.OuterFunc][.Class].func  (methods win over nesting)
        if cls and not self.func_stack:
            qname = f"{self.module.dotted_name}.{cls}.{node.name}"
        elif self.func_stack:
            qname = f"{self.module.dotted_name}." + ".".join(self.func_stack + [node.name])
        else:
            qname = f"{self.module.dotted_name}.{node.name}"

        collector = _CallCollector()
        collector.visit(node)
        segment = ast.get_source_segment(self.source, node) or ""
        info = FunctionInfo(
            name=node.name,
            qualified_name=qname,
            file=self.module.path,
            lineno=node.lineno,
            end_lineno=node.end_lineno or node.lineno,
            args=_format_args(node.args),
            docstring=ast.get_docstring(node) or "",
            source=segment,
            calls=collector.calls,
            decorators=[_decorator_name(d) for d in node.decorator_list],
            is_method=bool(cls and not self.func_stack),
            class_name=cls if not self.func_stack else None,
        )
        info.loc = segment.count("\n") + 1 if segment else 0
        self.module.functions.append(info)
        if cls and not self.func_stack:
            for c in self.module.classes:
                if c.qualified_name == f"{self.module.dotted_name}.{cls}":
                    c.methods.append(qname)
        # recurse for nested functions
        self.func_stack.append(node.name)
        for stmt in node.body:
            self.visit(stmt)
        self.func_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._record_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self._record_function(node)


def _dotted_name(root: str, rel_path: str) -> str:
    no_ext = os.path.splitext(rel_path)[0]
    parts = no_ext.split(os.sep)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else os.path.basename(root)


def parse_file(root: str, rel_path: str) -> ModuleInfo | None:
    abs_path = os.path.join(root, rel_path)
    try:
        with open(abs_path, "r", encoding="utf-8", errors="replace") as fh:
            source = fh.read()
    except OSError:
        return None
    try:
        tree = ast.parse(source, filename=rel_path)
    except SyntaxError:
        return None
    module = ModuleInfo(
        path=rel_path,
        dotted_name=_dotted_name(root, rel_path),
        docstring=ast.get_docstring(tree) or "",
        imports=[], functions=[], classes=[],
        loc=source.count("\n") + 1,
    )
    _ModuleVisitor(module, source).visit(tree)
    return module


def parse_project(root: str, name: str | None = None) -> Project:
    """Parse every ``.py`` file under *root* (skipping venvs/hidden dirs)."""
    root = os.path.abspath(root)
    project = Project(name=name or os.path.basename(root.rstrip(os.sep)) or "project",
                      root=root)
    skip_dirs = {".venv", "venv", ".git", "__pycache__", ".hg", ".tox",
                 "node_modules", ".eggs", "build", "dist", ".idea", ".vscode"}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs and not d.startswith(".")]
        for fn in sorted(filenames):
            if not fn.endswith(".py"):
                continue
            rel = os.path.relpath(os.path.join(dirpath, fn), root)
            mod = parse_file(root, rel)
            if mod is not None:
                project.modules.append(mod)
    project.modules.sort(key=lambda m: m.path)
    # The root package (__init__.py at the extraction root) otherwise takes the
    # arbitrary extraction folder name ("src"); use the real project name.
    root_base = os.path.basename(root)
    for m in project.modules:
        if m.path == "__init__.py" and m.dotted_name == root_base \
                and project.name != root_base:
            m.dotted_name = project.name
            for f in m.functions:
                f.qualified_name = project.name + f.qualified_name[len(root_base):]
            for c in m.classes:
                c.qualified_name = project.name + c.qualified_name[len(root_base):]
    return project
