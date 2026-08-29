"""Core review pipeline: ties diff, analysis, detectors, scoring, report."""
from __future__ import annotations

import os
from pathlib import Path

from .detectors import (
    collect_existing_functions,
    detect_duplicates,
    detect_one_use_classes,
    detect_pass_through_functions,
    detect_pass_through_layers,
    extract_new_symbols,
    walk_python_files,
)
from .git_diff import collect_diff, get_file_content, get_working_tree_file
from .llm import LLMConfig, review_scope, simplification_advice
from .python_analyzer import analyze_code, compute_delta
from .scoring import compute_scores, risk_level


def _env_llm_cfg() -> LLMConfig:
    return LLMConfig(
        api_key=os.environ.get("CODEREVIEW_API_KEY"),
        base_url=os.environ.get("CODEREVIEW_BASE_URL"),
        model=os.environ.get("CODEREVIEW_MODEL"),
    )


def _risk_for_delta(delta: int) -> str:
    if delta < 5:
        return "LOW"
    if delta < 20:
        return "MEDIUM"
    if delta < 50:
        return "HIGH"
    return "VERY HIGH"


def _size_risk(files: int, added: int) -> str:
    if files <= 2 and added <= 100:
        return "LOW"
    if files <= 6 and added <= 400:
        return "MEDIUM"
    return "HIGH"


def run_review(base: str, task: str, cwd: Path | None = None) -> dict:
    """Run the full review and return a structured report dict."""
    cwd = cwd or Path.cwd()
    diff = collect_diff(base, cwd)

    # Collect repository Python files (existing capabilities source).
    repo_files = walk_python_files(cwd)

    changed_python = [
        f for f in diff.files
        if f.path.endswith(".py") and f.status in ("added", "modified", "deleted")
    ]

    new_functions_all = []
    new_classes_all = []
    per_file_delta = {}
    fn_complexity_all = []  # (name, file, complexity) for every function in after-source
    total_before = {"complexity": 0, "loc": 0, "function_count": 0, "class_count": 0}
    total_after = {"complexity": 0, "loc": 0, "function_count": 0, "class_count": 0}

    for fc in changed_python:
        before_source = get_file_content(base, fc.path, cwd)
        after_source = None
        if fc.status == "deleted":
            after_source = None
        elif fc.status == "modified":
            after_source = get_working_tree_file(fc.path, cwd)
        else:  # added
            after_source = get_working_tree_file(fc.path, cwd)

        if before_source is None and after_source is None:
            continue

        before_m = analyze_code(before_source) if before_source else None
        after_m = analyze_code(after_source) if after_source else None

        if before_m:
            total_before["complexity"] += before_m.complexity
            total_before["loc"] += before_m.loc
            total_before["function_count"] += before_m.function_count
            total_before["class_count"] += before_m.class_count
        if after_m:
            total_after["complexity"] += after_m.complexity
            total_after["loc"] += after_m.loc
            total_after["function_count"] += after_m.function_count
            total_after["class_count"] += after_m.class_count
            fn_complexity_all.extend(
                (fn.name, fc.path, fn.complexity) for fn in after_m.functions
            )

        delta = compute_delta(before_m, after_m)
        if delta:
            per_file_delta[fc.path] = delta

        if after_source is not None and before_source is not None:
            funcs, classes = extract_new_symbols(before_source, after_source, fc.path)
            new_functions_all.extend(funcs)
            new_classes_all.extend(classes)
        elif after_source is not None:
            funcs, classes = extract_new_symbols(None, after_source, fc.path)
            new_functions_all.extend(funcs)
            new_classes_all.extend(classes)

    # Deterministic detectors
    abstractions = []
    abstractions += detect_one_use_classes(new_classes_all, repo_files)
    abstractions += detect_pass_through_functions(new_functions_all)
    abstractions += detect_pass_through_layers(new_functions_all)

    existing = collect_existing_functions(repo_files)
    duplicates = detect_duplicates(new_functions_all, existing)

    # LLM scope drift (optional)
    llm_cfg = _env_llm_cfg()
    scope_drift = []
    if llm_cfg.enabled:
        files_info = [
            {
                "file": f.path,
                "added": f.added_lines,
                "deleted": f.deleted_lines,
                "status": f.status,
            }
            for f in diff.files if f.status in ("added", "modified")
        ]
        scope = review_scope(llm_cfg, task, files_info)
        for f in scope.possibly_unrelated:
            scope_drift.append({
                "file": f,
                "reason": scope.reasons.get(f, ""),
                "similarity": scope.similarity.get(f),
                "matched_keywords": scope.matched_keywords.get(f, []),
            })

    # LLM simplification advice (optional)
    suggestions: list[str] = []
    if llm_cfg.enabled:
        findings_summary = {
            "abstractions": [
                {"name": a.name, "kind": a.kind, "reason": a.reason}
                for a in abstractions
            ],
            "duplicates": [
                {"new": d.new_name, "existing": d.existing_name, "confidence": d.confidence}
                for d in duplicates
            ],
            "scope_drift": [s["file"] for s in scope_drift],
        }
        suggestions = simplification_advice(llm_cfg, findings_summary)

    # Aggregate complexity delta across all changed Python files.
    complexity_delta = {
        "loc": {"before": total_before["loc"], "after": total_after["loc"],
                "delta": total_after["loc"] - total_before["loc"]},
        "function_count": {
            "before": total_before["function_count"],
            "after": total_after["function_count"],
            "delta": total_after["function_count"] - total_before["function_count"],
        },
        "class_count": {
            "before": total_before["class_count"],
            "after": total_after["class_count"],
            "delta": total_after["class_count"] - total_before["class_count"],
        },
        "complexity": {
            "before": total_before["complexity"],
            "after": total_after["complexity"],
            "delta": total_after["complexity"] - total_before["complexity"],
        },
    }

    total_complexity_before = total_before["complexity"]
    total_complexity_after = total_after["complexity"]
    pct = (
        (total_complexity_after - total_complexity_before) / total_complexity_before * 100
        if total_complexity_before else 0.0
    )

    # Top-N most complex functions after the change (complexity localization).
    fn_complexity_all.sort(key=lambda x: x[2], reverse=True)
    top_complexity = [
        {"name": name, "file": file, "complexity": cx, "over_threshold": cx > 20}
        for name, file, cx in fn_complexity_all[:10]
    ]

    score, breakdown = compute_scores(
        files_changed=diff.files_changed,
        lines_added=diff.added_lines,
        complexity_delta=complexity_delta,
        abstractions=abstractions,
        duplicates=duplicates,
        scope_drift=scope_drift,
    )

    return {
        "task": task,
        "base": base,
        "score": score,
        "risk": risk_level(score),
        "change_summary": {
            "files_changed": diff.files_changed,
            "lines_added": diff.added_lines,
            "lines_deleted": diff.deleted_lines,
            "new_functions": len(new_functions_all),
            "new_classes": len(new_classes_all),
            "size_risk": _size_risk(diff.files_changed, diff.added_lines),
        },
        "complexity": {
            "before": total_complexity_before,
            "after": total_complexity_after,
            "delta": total_complexity_after - total_complexity_before,
            "pct": pct,
            "risk": _risk_for_delta(total_complexity_after - total_complexity_before),
            "per_file": per_file_delta,
        },
        "abstractions": [
            {
                "name": a.name,
                "file": a.file,
                "kind": a.kind,
                "reason": a.reason,
            }
            for a in abstractions
        ],
        "duplicates": [
            {
                "new_name": d.new_name,
                "new_file": d.new_file,
                "existing_name": d.existing_name,
                "existing_file": d.existing_file,
                "confidence": d.confidence,
                "mergeable": d.mergeable,
                "merge_reason": d.merge_reason,
            }
            for d in duplicates
        ],
        "scope_drift": scope_drift,
        "suggestions": suggestions,
        "top_complexity": top_complexity,
        "breakdown": [
            {"label": b.label, "points": b.points, "max_points": b.max_points, "reason": b.reason}
            for b in breakdown
        ],
    }