from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from packages.core.citations.models import CitationContext

CITATION_MARKER_RE = re.compile(r"\[\s*(\d+)\s*\]")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?;])\s+|\n+")


@dataclass
class RegulatedCitationResult:
    answer: str
    claim_failures: list[str] = field(default_factory=list)
    hard_refused: bool = False


def _split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in SENTENCE_SPLIT_RE.split(text.strip()) if p.strip()]
    return parts if parts else ([text.strip()] if text.strip() else [])


def _split_paragraphs(text: str) -> list[list[str]]:
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text.strip()) if b.strip()]
    if not blocks:
        return [_split_sentences(text)] if text.strip() else []
    return [_split_sentences(block) for block in blocks]


def _is_question(sentence: str) -> bool:
    return sentence.rstrip().endswith("?")


def _has_valid_citation(sentence: str, valid_indices: set[int]) -> bool:
    markers = [int(m) for m in CITATION_MARKER_RE.findall(sentence)]
    return any(m in valid_indices for m in markers)


def _is_factual_sentence(
    sentence: str,
    profile: dict[str, Any],
    compiled_factual_patterns: list[re.Pattern[str]],
    compiled_exempt_patterns: list[re.Pattern[str]],
) -> bool:
    if _is_question(sentence):
        return False
    for pattern in compiled_exempt_patterns:
        if pattern.search(sentence):
            return False
    for pattern in compiled_factual_patterns:
        if pattern.search(sentence):
            return True
    factual_keywords = [str(k).lower() for k in (profile.get("factual_keywords") or []) if k]
    lowered = sentence.lower()
    if any(kw in lowered for kw in factual_keywords):
        return True
    if re.search(r"\d", sentence):
        return True
    if re.search(r"\b(is|are|was|were|has|have|will|can|must|should)\b", lowered):
        return len(sentence.split()) >= 4
    return False


def enforce_regulated_citations(
    answer: str,
    context: CitationContext,
    guardrails: dict[str, Any],
    *,
    compiled_factual_patterns: list[re.Pattern[str]],
    compiled_exempt_patterns: list[re.Pattern[str]],
) -> RegulatedCitationResult:
    """Conservative heuristic claim-level citation check — not semantic fact verification."""
    profile = guardrails.get("regulated_profile") or {}
    if not profile.get("require_claim_level_citations", True):
        return RegulatedCitationResult(answer=answer)

    refusal_phrase = str(
        profile.get("refusal_phrase") or "This information was not found in approved sources."
    ).strip()
    block_on_fail = bool(profile.get("block_on_claim_validation_fail", False))
    end_para_invalid = bool(profile.get("end_of_paragraph_citations_invalid", True))
    valid_indices = context.valid_indices

    claim_failures: list[str] = []
    output_paragraphs: list[str] = []

    for paragraph in _split_paragraphs(answer):
        processed: list[str] = []
        factual_flags: list[bool] = []

        for sentence in paragraph:
            factual = _is_factual_sentence(
                sentence,
                profile,
                compiled_factual_patterns,
                compiled_exempt_patterns,
            )
            factual_flags.append(factual)
            cited = _has_valid_citation(sentence, valid_indices)

            if factual and not cited:
                claim_failures.append(sentence)
                processed.append(refusal_phrase)
            else:
                processed.append(sentence)

        if end_para_invalid and len(paragraph) >= 2:
            factual_indices = [i for i, f in enumerate(factual_flags) if f]
            if len(factual_indices) >= 2:
                cited_indices = [
                    i for i in factual_indices if _has_valid_citation(paragraph[i], valid_indices)
                ]
                if cited_indices and max(cited_indices) == factual_indices[-1]:
                    for i in factual_indices[:-1]:
                        if not _has_valid_citation(paragraph[i], valid_indices):
                            if processed[i] != refusal_phrase:
                                claim_failures.append(paragraph[i])
                                processed[i] = refusal_phrase

        output_paragraphs.append(" ".join(processed))

    if claim_failures and block_on_fail:
        return RegulatedCitationResult(
            answer=refusal_phrase,
            claim_failures=claim_failures,
            hard_refused=True,
        )

    return RegulatedCitationResult(
        answer="\n\n".join(output_paragraphs).strip(),
        claim_failures=claim_failures,
    )
