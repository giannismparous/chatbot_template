from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from packages.core.domain.models import ChatResponse
from packages.core.eval.models import AssertionResult, EvalExpectations
from packages.core.retrieval.models import RetrievalOutcome


def evaluate_retrieval(expect: EvalExpectations, outcome: RetrievalOutcome) -> list[AssertionResult]:
    results: list[AssertionResult] = []
    top_ids = [c.id for c in outcome.chunks]
    combined_text = " ".join(
        [c.text for c in outcome.chunks]
        + [str(c.metadata.get("title", "")) for c in outcome.chunks]
    ).lower()

    if expect.expected_no_context is not None:
        results.append(
            _check(
                "expected_no_context",
                expect.expected_no_context,
                outcome.no_context,
            )
        )
    if expect.expected_chunk_ids:
        matched = any(cid in top_ids for cid in expect.expected_chunk_ids)
        results.append(
            _check(
                "expected_chunk_ids",
                expect.expected_chunk_ids,
                top_ids,
                passed=matched,
                detail="at least one expected chunk id in top-K",
            )
        )
    if expect.expected_top_k_contains:
        for token in expect.expected_top_k_contains:
            ok = token.lower() in combined_text
            results.append(
                _check(
                    "expected_top_k_contains",
                    token,
                    combined_text[:200],
                    passed=ok,
                )
            )
    return results


def evaluate_chat(expect: EvalExpectations, response: ChatResponse) -> list[AssertionResult]:
    results: list[AssertionResult] = []
    answer = response.answer or ""
    answer_lower = answer.lower()

    for token in expect.expected_contains:
        results.append(
            _check(
                "expected_contains",
                token,
                answer[:300],
                passed=token.lower() in answer_lower,
            )
        )
    for token in expect.expected_not_contains:
        results.append(
            _check(
                "expected_not_contains",
                token,
                answer[:300],
                passed=token.lower() not in answer_lower,
            )
        )
    if expect.expected_no_context is not None:
        actual = bool(response.trace.get("no_context"))
        results.append(_check("expected_no_context", expect.expected_no_context, actual))
    if expect.expected_requires_human is not None:
        results.append(
            _check(
                "expected_requires_human",
                expect.expected_requires_human,
                response.requires_human,
            )
        )
    if expect.expected_escalation is not None:
        actual_type = response.escalation.type if response.escalation else None
        if expect.expected_escalation.lower() == "null":
            passed = actual_type is None
            expected_display: Any = None
        else:
            passed = actual_type == expect.expected_escalation
            expected_display = expect.expected_escalation
        results.append(_check("expected_escalation", expected_display, actual_type, passed=passed))
    if expect.expected_sources_min_count is not None:
        results.append(
            _check(
                "expected_sources.min_count",
                expect.expected_sources_min_count,
                len(response.sources),
                passed=len(response.sources) >= expect.expected_sources_min_count,
            )
        )
    if expect.expected_sources_domains:
        hosts = [_host(s.url) for s in response.sources]
        for domain in expect.expected_sources_domains:
            ok = any(domain in h for h in hosts)
            results.append(
                _check(
                    "expected_sources.domains",
                    domain,
                    hosts,
                    passed=ok,
                )
            )
        for source in response.sources:
            url_lower = source.url.lower()
            forbidden = any(x in url_lower for x in ("drive.google.com", "internal://", "uploads/"))
            results.append(
                _check(
                    "expected_sources.no_internal_urls",
                    "no internal/drive urls",
                    source.url,
                    passed=not forbidden,
                )
            )
    return results


def all_passed(results: list[AssertionResult]) -> bool:
    return bool(results) and all(r.passed for r in results)


def _host(url: str) -> str:
    try:
        return (urlparse(url).netloc or "").lower()
    except Exception:
        return ""


def _check(
    name: str,
    expected: Any,
    actual: Any,
    *,
    passed: bool | None = None,
    detail: str = "",
) -> AssertionResult:
    ok = passed if passed is not None else expected == actual
    return AssertionResult(name=name, expected=expected, actual=actual, passed=ok, detail=detail)
