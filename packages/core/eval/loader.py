from __future__ import annotations

from pathlib import Path
from typing import Any

from packages.config.loaders import load_yaml
from packages.core.eval.models import CASE_CATEGORIES, EvalCase, EvalExpectations, EvalSuiteConfig


class EvalSchemaError(ValueError):
    pass


def load_eval_suite(clients_root: Path, client_id: str) -> EvalSuiteConfig:
    path = clients_root / client_id / "tests" / "eval_suite.yaml"
    if not path.is_file():
        raise EvalSchemaError(f"Missing eval suite: {path}")
    raw = load_yaml(str(path))
    if not isinstance(raw, dict):
        raise EvalSchemaError(f"Invalid eval suite YAML: {path}")
    return EvalSuiteConfig.from_dict(client_id, raw)


def load_eval_cases(clients_root: Path, client_id: str) -> list[EvalCase]:
    cases_dir = clients_root / client_id / "tests" / "cases"
    if not cases_dir.is_dir():
        raise EvalSchemaError(f"Missing eval cases directory: {cases_dir}")

    cases: list[EvalCase] = []
    yaml_files = sorted(cases_dir.glob("*.yaml")) + sorted(cases_dir.glob("*.yml"))
    if not yaml_files:
        raise EvalSchemaError(f"No case files in {cases_dir}")

    for path in yaml_files:
        raw = load_yaml(str(path))
        if not isinstance(raw, dict):
            raise EvalSchemaError(f"Invalid case file: {path}")
        file_cases = raw.get("cases")
        if not isinstance(file_cases, list):
            raise EvalSchemaError(f"Case file must contain 'cases' list: {path}")
        for idx, item in enumerate(file_cases):
            cases.append(_parse_case(item, source=f"{path.name}[{idx}]"))

    if not cases:
        raise EvalSchemaError("Eval suite contains no cases")
    _validate_cases(cases)
    return cases


def _parse_case(raw: Any, *, source: str) -> EvalCase:
    if not isinstance(raw, dict):
        raise EvalSchemaError(f"Case must be a mapping: {source}")
    case_id = str(raw.get("id") or "").strip()
    category = str(raw.get("category") or "").strip()
    message = str(raw.get("message") or "").strip()
    if not case_id:
        raise EvalSchemaError(f"Case missing id: {source}")
    if category not in CASE_CATEGORIES:
        raise EvalSchemaError(f"Invalid category {category!r} in case {case_id}")
    if not message:
        raise EvalSchemaError(f"Case {case_id} missing message")
    history_raw = raw.get("history") or []
    history: list[dict[str, str]] = []
    if isinstance(history_raw, list):
        for turn in history_raw:
            if isinstance(turn, dict) and turn.get("role") and turn.get("content") is not None:
                history.append({"role": str(turn["role"]), "content": str(turn["content"])})
    expect_raw = raw.get("expect")
    if not isinstance(expect_raw, dict):
        raise EvalSchemaError(f"Case {case_id} missing expect mapping")
    return EvalCase(
        id=case_id,
        category=category,
        message=message,
        mode=str(raw["mode"]).strip() if raw.get("mode") else None,
        top_k=int(raw.get("top_k") or 5),
        history=history,
        expect=EvalExpectations.from_dict(expect_raw),
    )


def _validate_cases(cases: list[EvalCase]) -> None:
    seen: set[str] = set()
    for case in cases:
        if case.id in seen:
            raise EvalSchemaError(f"Duplicate case id: {case.id}")
        seen.add(case.id)
