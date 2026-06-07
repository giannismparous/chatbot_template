from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from packages.core.eval.models import EvalReport


REVIEWER_COLUMNS = [
    "case_id",
    "category",
    "question",
    "answer",
    "confidence",
    "requires_human",
    "escalation_type",
    "source_1_title",
    "source_1_url",
    "source_2_title",
    "source_2_url",
    "trace_id",
    "index_version",
    "reviewer_grade",
    "reviewer_notes",
    "run_id",
]


def export_reviewer_csv(path: Path, cases: list[dict[str, Any]], report: EvalReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=REVIEWER_COLUMNS)
        writer.writeheader()
        for case in cases:
            writer.writerow(_reviewer_row(case, report))


def export_reviewer_xlsx(path: Path, cases: list[dict[str, Any]], report: EvalReport) -> None:
    try:
        from openpyxl import Workbook
    except ImportError:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "reviewer"
    ws.append(REVIEWER_COLUMNS)
    for case in cases:
        ws.append([_reviewer_row(case, report).get(col, "") for col in REVIEWER_COLUMNS])
    wb.save(path)


def _reviewer_row(case: dict[str, Any], report: EvalReport) -> dict[str, str]:
    sources = case.get("sources") or []
    s1 = sources[0] if len(sources) > 0 else {}
    s2 = sources[1] if len(sources) > 1 else {}
    return {
        "case_id": str(case.get("id") or ""),
        "category": str(case.get("category") or ""),
        "question": str(case.get("message") or ""),
        "answer": str(case.get("answer_preview") or ""),
        "confidence": "",
        "requires_human": str(case.get("requires_human") if case.get("requires_human") is not None else ""),
        "escalation_type": str(case.get("escalation_type") or ""),
        "source_1_title": str(s1.get("title") or ""),
        "source_1_url": str(s1.get("url") or ""),
        "source_2_title": str(s2.get("title") or ""),
        "source_2_url": str(s2.get("url") or ""),
        "trace_id": str(case.get("trace_id") or ""),
        "index_version": str(report.evaluated_index_version or ""),
        "reviewer_grade": "",
        "reviewer_notes": "",
        "run_id": report.run_id,
    }
