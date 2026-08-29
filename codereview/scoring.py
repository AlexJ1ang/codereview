"""Explainable heuristic scoring for implementation overhead.

Higher score = more overhead. 0-100 range, broken down by component.
"""
from __future__ import annotations

from dataclasses import dataclass

WEIGHTS = {
    "change_size": 20,
    "complexity_delta": 30,
    "abstraction": 20,
    "duplicate": 15,
    "scope_drift": 15,
}

# Score interactions are capped so single components can't dominate.
_CHANGE_SIZE_CAP = 20
_COMPLEXITY_DELTA_CAP = 30
_ABSTRACTION_CAP = 20
_DUPLICATE_CAP = 15
_SCOPE_DRIFT_CAP = 15


@dataclass
class ScoreBreakdown:
    label: str
    points: int
    max_points: int
    reason: str


def risk_level(score: float) -> str:
    if score < 30:
        return "LOW"
    if score < 60:
        return "MEDIUM"
    if score < 80:
        return "HIGH"
    return "VERY HIGH"


def _scale(value: float, low: float, high: float) -> float:
    """Normalize value into [0, 1] clamped at high."""
    if high <= low:
        return 0.0
    return max(0.0, min(1.0, value / high))


def score_change_size(files_changed: int, lines_added: int) -> ScoreBreakdown:
    # 1-2 files / <=100 lines is a reasonable baseline; 10+ files signals scope creep.
    if files_changed <= 2 and lines_added <= 100:
        points = 0.0
    else:
        file_ratio = _scale(files_changed, 3, 10)
        line_ratio = _scale(lines_added, 101, 300)
        ratio = max(file_ratio, line_ratio)
        points = round(ratio * WEIGHTS["change_size"], 1)
    return ScoreBreakdown(
        label="Change Size",
        points=points,
        max_points=WEIGHTS["change_size"],
        reason=f"{files_changed} files, {lines_added} lines added",
    )


def score_complexity_delta(complexity_delta: dict) -> ScoreBreakdown:
    before = complexity_delta["complexity"]["before"]
    after = complexity_delta["complexity"]["after"]
    delta = complexity_delta["complexity"]["delta"]
    # 20% complexity growth is notable; 100%+ is severe.
    pct = (delta / before * 100) if before else 0.0
    ratio = _scale(max(delta, 0), 0, max(before * 0.5, 15))
    points = round(ratio * WEIGHTS["complexity_delta"], 1)
    direction = f"+{delta} (+{pct:.0f}%)" if delta > 0 else f"{delta} ({pct:.0f}%)"
    return ScoreBreakdown(
        label="Complexity Delta",
        points=points,
        max_points=WEIGHTS["complexity_delta"],
        reason=f"complexity {before} -> {after} ({direction})",
    )


def score_abstractions(abstractions: list) -> ScoreBreakdown:
    if not abstractions:
        return ScoreBreakdown(
            label="Abstraction",
            points=0.0,
            max_points=WEIGHTS["abstraction"],
            reason="no unnecessary abstractions detected",
        )
    # First finding is most informative; cap contribution.
    ratio = _scale(len(abstractions), 0, 3)
    points = round(ratio * WEIGHTS["abstraction"], 1)
    names_list = []
    for a in abstractions[:3]:
        if isinstance(a, dict):
            names_list.append(a.get("name", a.get("kind", "?")))
        else:
            names_list.append(getattr(a, "name", getattr(a, "kind", "?")))
    names = ", ".join(names_list)
    return ScoreBreakdown(
        label="Abstraction",
        points=points,
        max_points=WEIGHTS["abstraction"],
        reason=f"{len(abstractions)} finding(s): {names}",
    )


def score_duplicates(duplicates: list) -> ScoreBreakdown:
    # exact/high-confidence duplicates weigh more
    # Handle both dict and dataclass inputs
    weighted = 0.0
    for d in duplicates:
        if isinstance(d, dict):
            conf = d.get("confidence", "")
        else:
            conf = getattr(d, "confidence", "")
        weighted += 1.0 if conf == "HIGH" else 0.5
    ratio = _scale(weighted, 0, 4)
    points = round(ratio * WEIGHTS["duplicate"], 1)
    return ScoreBreakdown(
        label="Duplicate Logic",
        points=points,
        max_points=WEIGHTS["duplicate"],
        reason=f"{len(duplicates)} duplicate(s)",
    )


def score_scope_drift(scope_drift: list) -> ScoreBreakdown:
    if not scope_drift:
        return ScoreBreakdown(
            label="Scope Drift",
            points=0.0,
            max_points=WEIGHTS["scope_drift"],
            reason="no scope drift detected",
        )
    ratio = _scale(len(scope_drift), 0, 3)
    points = round(ratio * WEIGHTS["scope_drift"], 1)
    files = ", ".join(s["file"] for s in scope_drift[:3])
    return ScoreBreakdown(
        label="Scope Drift",
        points=points,
        max_points=WEIGHTS["scope_drift"],
        reason=f"{len(scope_drift)} file(s) possibly unrelated: {files}",
    )


def compute_scores(
    files_changed: int,
    lines_added: int,
    complexity_delta: dict,
    abstractions: list,
    duplicates: list,
    scope_drift: list,
) -> tuple[float, list[ScoreBreakdown]]:
    breakdown = [
        score_change_size(files_changed, lines_added),
        score_complexity_delta(complexity_delta),
        score_abstractions(abstractions),
        score_duplicates(duplicates),
        score_scope_drift(scope_drift),
    ]
    total = sum(b.points for b in breakdown)
    return round(total, 1), breakdown