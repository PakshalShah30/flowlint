"""Renders findings as a grouped table or as JSON for CI consumption."""

from __future__ import annotations

import json
import os
from collections import defaultdict

from .models import Finding

SEVERITY_ORDER = {"error": 0, "warning": 1}


def _wrap(text: str, width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > width and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines or [""]


def render_table(findings: list[Finding]) -> str:
    if not findings:
        return "No findings. FlowLint has nothing to report on the scanned Flows."

    by_file: dict[str, list[Finding]] = defaultdict(list)
    for f in findings:
        by_file[f.file].append(f)

    out_lines: list[str] = []
    for file_path in sorted(by_file):
        file_findings = sorted(
            by_file[file_path],
            key=lambda f: (SEVERITY_ORDER.get(f.severity, 9), f.rule_id, f.element or ""),
        )
        out_lines.append(os.path.basename(file_path))
        out_lines.append("-" * len(os.path.basename(file_path)))
        for f in file_findings:
            header = f"  [{f.rule_id}] {f.severity.upper():7s} element: {f.element}"
            out_lines.append(header)
            for line in _wrap(f.message, 96):
                out_lines.append(f"      {line}")
        out_lines.append("")

    total = len(findings)
    errors = sum(1 for f in findings if f.severity == "error")
    warnings = sum(1 for f in findings if f.severity == "warning")
    files = len(by_file)
    out_lines.append(
        f"{total} finding(s) across {files} file(s): {errors} error(s), {warnings} warning(s)."
    )
    return "\n".join(out_lines)


def render_json(findings: list[Finding]) -> str:
    payload = {
        "count": len(findings),
        "findings": [f.as_dict() for f in findings],
    }
    return json.dumps(payload, indent=2, sort_keys=False)
