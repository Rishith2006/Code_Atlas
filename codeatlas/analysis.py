"""Complexity, risk scoring and optimality analysis for CodeAtlas.

Risk model (0-100, higher = riskier):
    35 pts  cyclomatic complexity      (cap 20)
    20 pts  lines of code             (cap 200)
    15 pts  fan-out (functions called) (cap 10)
    10 pts  fan-in  (callers)          (cap 10)
    10 pts  missing docstring
    10 pts  max nesting depth          (cap 5)

Levels: Low < 30, Medium < 55, High < 75, Critical >= 75.
"""
from __future__ import annotations

import ast

from .parser import FunctionInfo, Project

_DECISION_NODES = (
    ast.If, ast.For, ast.AsyncFor, ast.While,
    ast.ExceptHandler, ast.With, ast.AsyncWith,
)
_COMP_NODES = (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)


def cyclomatic_complexity(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """McCabe-style complexity. Nested function defs are excluded."""
    score = 1

    def visit(node: ast.AST):
        nonlocal score
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue  # don't count nested scopes
            if isinstance(child, _DECISION_NODES):
                score += 1
            elif isinstance(child, ast.BoolOp):
                score += len(child.values) - 1
            elif isinstance(child, (ast.IfExp, ast.Assert)):
                score += 1
            elif isinstance(child, _COMP_NODES):
                score += 1
            visit(child)

    visit(func_node)
    return score


def max_nesting(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """Deepest nesting of control-flow blocks (excluding nested defs)."""
    best = 0

    def visit(node: ast.AST, depth: int):
        nonlocal best
        best = max(best, depth)
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            if isinstance(child, (ast.If, ast.For, ast.AsyncFor, ast.While,
                                  ast.Try, ast.TryStar, ast.With, ast.AsyncWith,
                                  ast.ExceptHandler)):
                visit(child, depth + 1)
            else:
                visit(child, depth)

    visit(func_node, 0)
    return best


def _score_function_source(func: FunctionInfo) -> tuple[int, int]:
    """Return (complexity, max_nesting) computed from the function's source."""
    try:
        node = ast.parse(func.source).body[0]
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return cyclomatic_complexity(node), max_nesting(node)
    except (SyntaxError, IndexError):
        pass
    return 1, 0


def risk_score(func: FunctionInfo, fan_in: int = 0, fan_out: int = 0) -> tuple[float, str]:
    complexity, nesting = _score_function_source(func)
    func.complexity = complexity
    func.max_nesting = nesting

    parts = [
        min(complexity, 20) / 20 * 35,
        min(func.loc, 200) / 200 * 20,
        min(fan_out, 10) / 10 * 15,
        min(fan_in, 10) / 10 * 10,
        0 if func.docstring.strip() else 10,
        min(nesting, 5) / 5 * 10,
    ]
    score = round(sum(parts), 1)
    if score < 30:
        level = "Low"
    elif score < 55:
        level = "Medium"
    elif score < 75:
        level = "High"
    else:
        level = "Critical"
    return score, level


def optimality_suggestions(func: FunctionInfo) -> list[str]:
    """Heuristic maintainability hints for a function."""
    tips = []
    if func.complexity >= 10:
        tips.append(f"High cyclomatic complexity ({func.complexity}): split into smaller helpers.")
    elif func.complexity >= 6:
        tips.append(f"Moderate complexity ({func.complexity}): consider extracting branches.")
    if func.loc > 80:
        tips.append(f"Long function ({func.loc} lines): extract logical blocks into helpers.")
    if len(func.args) > 5:
        tips.append(f"Many parameters ({len(func.args)}): group related args into a dataclass/config object.")
    if func.max_nesting >= 4:
        tips.append(f"Deep nesting ({func.max_nesting}): use early returns / guard clauses.")
    if not func.docstring.strip():
        tips.append("Missing docstring: add a one-line summary plus arg/return docs.")
    if len(func.calls) > 12:
        tips.append(f"High fan-out ({len(func.calls)} call sites): this function knows about many collaborators.")
    return tips


def analyze_project(project: Project, fan_in: dict, fan_out: dict) -> None:
    """Fill complexity / risk / suggestions on every function, in place."""
    for func in project.all_functions():
        fi = fan_in.get(func.qualified_name, 0)
        fo = fan_out.get(func.qualified_name, 0)
        func.risk_score, func.risk_level = risk_score(func, fi, fo)
        func.suggestions = optimality_suggestions(func)


def riskiest_functions(project: Project, n: int = 10) -> list[FunctionInfo]:
    return sorted(project.all_functions(),
                  key=lambda f: (-f.risk_score, f.qualified_name))[:n]
