"""Detection of suspicious abstractions and duplicate capabilities.

Everything here is deterministic static analysis. LLM-based semantic review
lives in `llm.py` and is optional.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

from .python_analyzer import analyze_code

# Name fragments that often signal a single-purpose wrapper.
SUSPICIOUS_CLASS_SUFFIXES = (
    "Manager",
    "Handler",
    "Processor",
    "Factory",
    "Service",
    "Context",
    "Wrapper",
    "Helper",
    "Util",
    "Controller",
)


@dataclass
class NewFunction:
    name: str
    file: str
    loc: int
    arg_count: int
    arg_names: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    body_stmt_count: int = 0
    return_call_only: bool = False


@dataclass
class NewClass:
    name: str
    file: str
    method_count: int
    method_names: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    has_state: bool = False
    has_inheritance: bool = False


@dataclass
class AbstractionFinding:
    name: str
    file: str
    kind: str  # one-use-class, pass-through-function, pass-through-layer
    reason: str


@dataclass
class DuplicateFinding:
    new_name: str
    new_file: str
    existing_name: str
    existing_file: str
    confidence: str  # HIGH / MEDIUM
    # Merge analysis (only for high-confidence pairs).
    mergeable: bool = False
    merge_reason: str = ""


def walk_python_files(root: Path) -> list[Path]:
    ignore = {
        ".venv", "venv", "node_modules", "dist", "build",
        "__pycache__", ".git", ".idea", ".vscode",
    }
    out: list[Path] = []
    for p in root.rglob("*.py"):
        if any(part in ignore for part in p.parts):
            continue
        out.append(p)
    return out


def _called_names(body: list[ast.stmt]) -> list[str]:
    names: list[str] = []
    for node in ast.walk(ast.Module(body=body, type_ignores=[])):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                names.append(func.id)
            elif isinstance(func, ast.Attribute):
                names.append(func.attr)
    return names


def _class_has_state(node: ast.ClassDef) -> bool:
    """True if the class assigns any instance/class attribute."""
    for n in ast.walk(node):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name) and t.id not in ("__all__", "__slots__"):
                    return True
        elif isinstance(n, ast.AnnAssign):
            if isinstance(n.target, ast.Name):
                return True
    return False


def _return_call_only(body: list[ast.stmt]) -> bool:
    """True if body is exactly `return f(...)`."""
    if len(body) != 1:
        return False
    stmt = body[0]
    if not isinstance(stmt, ast.Return) or stmt.value is None:
        return False
    return isinstance(stmt.value, ast.Call)


def _top_level_names(tree: ast.Module) -> set[str]:
    return {
        n.name
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }


def extract_new_symbols(
    before_source: str | None, after_source: str, file: str
) -> tuple[list[NewFunction], list[NewClass]]:
    """Extract top-level functions/classes added between before and after.

    Tolerates syntactically invalid sources (e.g. AI-generated code that
    does not yet parse): unparseable "after" yields no new symbols, and an
    unparseable "before" is treated as empty.
    """
    # If before_source is None (new file), everything is new
    if before_source is None:
        before_names: set[str] = set()
    else:
        try:
            before_tree = ast.parse(before_source)
        except SyntaxError:
            before_tree = None
        before_names = _top_level_names(before_tree) if before_tree else set()

    try:
        after_tree = ast.parse(after_source)
    except SyntaxError:
        return [], []

    new_functions: list[NewFunction] = []
    new_classes: list[NewClass] = []

    for node in after_tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in before_names:
                continue
            new_functions.append(
                NewFunction(
                    name=node.name,
                    file=file,
                    loc=node.end_lineno - node.lineno + 1 if node.end_lineno else 1,
                    arg_count=len(node.args.args),
                    arg_names=[a.arg for a in node.args.args],
                    calls=_called_names(node.body),
                    body_stmt_count=len(node.body),
                    return_call_only=_return_call_only(node.body),
                )
            )
        elif isinstance(node, ast.ClassDef):
            if node.name in before_names:
                continue
            methods = [
                n for n in node.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            calls: list[str] = []
            for m in methods:
                calls.extend(_called_names(m.body))
            new_classes.append(
                NewClass(
                    name=node.name,
                    file=file,
                    method_count=len(methods),
                    method_names=[m.name for m in methods],
                    calls=calls,
                    has_state=_class_has_state(node),
                    has_inheritance=len(node.bases) > 0,
                )
            )

    return new_functions, new_classes


def _count_references(name: str, repo_files: list[Path], defining_file: str) -> int:
    """Count textual references to a name across repository source files."""
    pattern = re.compile(rf"\b{re.escape(name)}\b")
    count = 0
    for p in repo_files:
        if p.name == Path(defining_file).name:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        count += len(pattern.findall(text))
    return count


def detect_one_use_classes(
    new_classes: list[NewClass],
    repo_files: list[Path],
) -> list[AbstractionFinding]:
    findings: list[AbstractionFinding] = []
    for c in new_classes:
        public_methods = [m for m in c.method_names if not m.startswith("_")]
        if len(public_methods) != 1:
            continue
        if c.has_state or c.has_inheritance:
            continue
        # More lenient: if no repo files, assume single caller
        refs = _count_references(c.name, repo_files, c.file) if repo_files else 0
        if refs <= 1:
            findings.append(
                AbstractionFinding(
                    name=c.name,
                    file=c.file,
                    kind="one-use-class",
                    reason=(
                        f"{refs} reference(s) outside definition, no state, "
                        f"single public method ({public_methods[0]})"
                    ),
                )
            )
    return findings


def detect_pass_through_functions(
    functions: list[NewFunction],
) -> list[AbstractionFinding]:
    findings: list[AbstractionFinding] = []
    for f in functions:
        if f.loc <= 3 and len(f.calls) == 1 and f.body_stmt_count <= 2:
            findings.append(
                AbstractionFinding(
                    name=f.name,
                    file=f.file,
                    kind="pass-through-function",
                    reason=(
                        f"body is just a call to {f.calls[0]}, no extra logic"
                    ),
                )
            )
    return findings


def detect_pass_through_layers(
    functions: list[NewFunction],
) -> list[AbstractionFinding]:
    by_name = {f.name: f for f in functions}
    findings: list[AbstractionFinding] = []
    for f in functions:
        if f.loc > 3 or len(f.calls) != 1:
            continue
        target = f.calls[0]
        if target in by_name:
            target_fn = by_name[target]
            next_hop = ", ".join(target_fn.calls) or "none"
            findings.append(
                AbstractionFinding(
                    name=f.name,
                    file=f.file,
                    kind="pass-through-layer",
                    reason=(
                        f"{f.name} -> {target} -> {next_hop}; "
                        "no business logic in between"
                    ),
                )
            )
    return findings


def _name_similarity(a: str, b: str) -> float:
    def norm(s: str) -> str:
        s = re.sub(r"(?<!^)(?=[A-Z])", "_", s).lower()
        return re.sub(r"[^a-z0-9_]", "", s)

    na, nb = norm(a), norm(b)
    if na == nb:
        return 1.0
    if not na or not nb:
        return 0.0
    common = 0
    for ca, cb in zip(na, nb):
        if ca == cb:
            common += 1
        else:
            break
    return common / max(len(na), len(nb))


def collect_existing_functions(
    repo_files: list[Path],
    exclude_file: str | None = None,
) -> dict[str, tuple[str, list[str]]]:
    """Collect map of function/method name -> (file path, arg names)."""
    result: dict[str, tuple[str, list[str]]] = {}
    for p in repo_files:
        if exclude_file and p.name == Path(exclude_file).name:
            continue
        try:
            source = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        metrics = analyze_code(source)
        if metrics is None:
            continue
        for f in metrics.functions:
            result.setdefault(f.name, (str(p), list(f.arg_names)))
        for c in metrics.classes:
            for m in c.method_names:
                result.setdefault(f"{c.name}.{m}", (str(p), []))
    return result


def detect_duplicates(
    new_functions: list[NewFunction],
    existing: dict[str, tuple[str, list[str]]],
) -> list[DuplicateFinding]:
    findings: list[DuplicateFinding] = []
    for nf in new_functions:
        if nf.name in existing and existing[nf.name][0] != nf.file:
            existing_file, existing_args = existing[nf.name]
            new_args = getattr(nf, "arg_names", [])
            mergeable = existing_args == new_args
            merge_reason = (
                f"identical signature {new_args}, can extract shared helper"
                if mergeable
                else (
                    f"signature differs: existing={existing_args}, new={new_args}"
                    if existing_args
                    else "existing signature unknown (method or no args)"
                )
            )
            findings.append(
                DuplicateFinding(
                    new_name=nf.name,
                    new_file=nf.file,
                    existing_name=nf.name,
                    existing_file=existing_file,
                    confidence="HIGH",
                    mergeable=mergeable,
                    merge_reason=merge_reason,
                )
            )
            continue
        best_name, best_sim = None, 0.0
        for existing_name in existing:
            sim = _name_similarity(nf.name, existing_name)
            if sim > best_sim:
                best_name, best_sim = existing_name, sim
        if best_name is not None and best_sim >= 0.6:
            findings.append(
                DuplicateFinding(
                    new_name=nf.name,
                    new_file=nf.file,
                    existing_name=best_name,
                    existing_file=existing[best_name][0],
                    confidence="HIGH" if best_sim >= 1.0 else "MEDIUM",
                )
            )
    return findings
