"""Lightweight Python static analysis using the `ast` standard library.

The goal is a *delta* — before vs after — not an authoritative complexity figure.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field

# Node types that contribute to complexity.
BRANCH_NODES = (
    ast.If,
    ast.For,
    ast.While,
    ast.Try,
    ast.ExceptHandler,
    ast.Match,
    ast.BoolOp,
    ast.comprehension,
)


@dataclass
class FunctionInfo:
    name: str
    lineno: int
    loc: int
    complexity: int
    arg_count: int
    is_method: bool = False
    arg_names: list[str] = field(default_factory=list)


@dataclass
class ClassInfo:
    name: str
    lineno: int
    loc: int
    method_count: int
    method_names: list[str] = field(default_factory=list)


@dataclass
class ModuleMetrics:
    loc: int = 0
    function_count: int = 0
    class_count: int = 0
    complexity: int = 0
    max_function_length: int = 0
    max_nesting_depth: int = 0
    functions: list[FunctionInfo] = field(default_factory=list)
    classes: list[ClassInfo] = field(default_factory=list)


def _node_loc(node: ast.AST) -> int:
    end = getattr(node, "end_lineno", None)
    if end is None:
        return 1
    return end - node.lineno + 1


def _complexity_of(body: list[ast.stmt]) -> int:
    total = 1  # baseline for the function/module body
    for node in body:
        for sub in ast.walk(node):
            if isinstance(sub, BRANCH_NODES):
                total += 1
    return total


def _nesting_depth(body: list[ast.stmt]) -> int:
    max_depth = 0

    def walk(node: ast.AST, depth: int) -> None:
        nonlocal max_depth
        max_depth = max(max_depth, depth)
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue  # don't count nested definitions' bodies
            walk(child, depth + 1)

    for stmt in body:
        walk(stmt, 0)
    return max_depth


class _Collector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.metrics = ModuleMetrics()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._record_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._record_function(node)

    def _record_function(self, node: ast.AST) -> None:
        loc = _node_loc(node)
        complexity = _complexity_of(node.body)
        args = getattr(node, "args", ast.arguments())
        arg_count = len(args.args)
        arg_names = [a.arg for a in args.args]
        self.metrics.function_count += 1
        self.metrics.max_function_length = max(self.metrics.max_function_length, loc)
        self.metrics.complexity += complexity
        self.metrics.functions.append(
            FunctionInfo(
                name=node.name,
                lineno=node.lineno,
                loc=loc,
                complexity=complexity,
                arg_count=arg_count,
                arg_names=arg_names,
            )
        )
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        loc = _node_loc(node)
        methods = [
            n
            for n in node.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        method_names = [m.name for m in methods]
        self.metrics.class_count += 1
        self.metrics.classes.append(
            ClassInfo(
                name=node.name,
                lineno=node.lineno,
                loc=loc,
                method_count=len(methods),
                method_names=method_names,
            )
        )
        for m in methods:
            self.visit(m)
        for child in node.body:
            if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.visit(child)


def analyze_code(source: str) -> ModuleMetrics | None:
    """Analyze Python source; return metrics or None if unparseable."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    collector = _Collector()
    collector.visit(tree)

    metrics = collector.metrics
    metrics.loc = len(source.splitlines())
    metrics.max_nesting_depth = _nesting_depth(tree.body)
    return metrics


def compute_delta(before: ModuleMetrics | None, after: ModuleMetrics | None) -> dict:
    """Compare before/after metrics and produce a delta dict.

    Returns an empty dict if either side is missing.
    """
    if before is None or after is None:
        return {}
    return {
        "loc": {"before": before.loc, "after": after.loc,
                "delta": after.loc - before.loc},
        "function_count": {
            "before": before.function_count,
            "after": after.function_count,
            "delta": after.function_count - before.function_count,
        },
        "class_count": {
            "before": before.class_count,
            "after": after.class_count,
            "delta": after.class_count - before.class_count,
        },
        "complexity": {
            "before": before.complexity,
            "after": after.complexity,
            "delta": after.complexity - before.complexity,
        },
        "max_function_length": {
            "before": before.max_function_length,
            "after": after.max_function_length,
            "delta": after.max_function_length - before.max_function_length,
        },
        "max_nesting_depth": {
            "before": before.max_nesting_depth,
            "after": after.max_nesting_depth,
            "delta": after.max_nesting_depth - before.max_nesting_depth,
        },
    }