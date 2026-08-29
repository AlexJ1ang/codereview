"""Render the review report as text or JSON."""
from __future__ import annotations

import json


def render_text(report: dict) -> str:
    lines: list[str] = []
    tools = [
        "CodeReview Report",
        "================",
        "",
        f"Task",
        f"{report['task']}",
        "",
        f"Base",
        f"{report['base']}",
    ]
    lines.extend(tools)

    lines.append("")
    lines.append("Change Summary")
    lines.append("--------------")
    cs = report["change_summary"]
    lines.append(f"Files Changed:    {cs['files_changed']}")
    lines.append(f"Lines Added:      {cs['lines_added']}")
    lines.append(f"Lines Deleted:    {cs['lines_deleted']}")
    lines.append(f"New Functions:    {cs['new_functions']}")
    lines.append(f"New Classes:      {cs['new_classes']}")
    lines.append(f"Change Size Risk: {cs['size_risk']}")

    lines.append("")
    lines.append("Complexity Delta")
    lines.append("----------------")
    comp = report["complexity"]
    lines.append(
        f"Before:            {comp['before']}  "
        f"After: {comp['after']}  "
        f"Delta: {comp['delta']:+d} ({comp['pct']:+.1f}%)"
    )
    lines.append(f"Risk:              {comp['risk']}")

    if report.get("top_complexity"):
        lines.append("")
        lines.append("Top Complexity Functions")
        lines.append("------------------------")
        for t in report["top_complexity"]:
            flag = "  [OVER 20, split recommended]" if t["over_threshold"] else ""
            lines.append(f"* {t['name']} ({t['file']}): {t['complexity']}{flag}")

    if report.get("abstractions"):
        lines.append("")
        lines.append("Abstractions")
        lines.append("------------")
        for a in report["abstractions"]:
            lines.append(f"* {a['kind']}: {a['name']} ({a['file']})")
            lines.append(f"    {a['reason']}")

    if report.get("duplicates"):
        lines.append("")
        lines.append("Duplicate Logic")
        lines.append("---------------")
        for d in report["duplicates"]:
            lines.append(
                f"* {d['confidence']}: {d['new_name']} ({d['new_file']}) "
                f"~ {d['existing_name']} ({d['existing_file']})"
            )

    if report.get("scope_drift"):
        lines.append("")
        lines.append("Scope Drift")
        lines.append("-----------")
        for s in report["scope_drift"]:
            sim = s.get("similarity")
            sim_str = f" (similarity {sim:.2f})" if isinstance(sim, (int, float)) else ""
            lines.append(f"* {s['file']}{sim_str}: {s['reason']}")
            kws = s.get("matched_keywords") or []
            if kws:
                lines.append(f"    task keywords matched: {', '.join(kws)}")

    if report.get("suggestions"):
        lines.append("")
        lines.append("Suggestions")
        lines.append("-----------")
        for s in report["suggestions"]:
            lines.append(f"* {s}")

    lines.append("")
    lines.append("Implementation Overhead")
    lines.append("-----------------------")
    lines.append(f"Score: {report['score']} / 100")
    lines.append(f"Risk:  {report['risk']}")

    return "\n".join(lines)


def render_json(report: dict) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2)