from __future__ import annotations

import re

_SENTENCE_END_RE = re.compile(r"[.!?;][\"')\]]*\s*$")
_TRAILING_CITATIONS_RE = re.compile(r"(?:\s*\[\d+(?:,\s*\d+)*\])+\s*$")


def looks_incomplete_answer(text: str) -> bool:
    """Heuristic for answers cut off mid-sentence (often max_output_tokens)."""
    stripped = (text or "").rstrip()
    if not stripped:
        return False

    body = _TRAILING_CITATIONS_RE.sub("", stripped).rstrip()
    if not body:
        return False
    if _SENTENCE_END_RE.search(body):
        return False

    tail = body.split()[-1] if body.split() else ""
    if len(tail) <= 2:
        return True
    if len(tail) <= 4 and tail[-1].isalpha() and not tail.endswith(("]", ")", '"', "'")):
        return True
    return True


def trim_to_last_complete_sentence(text: str) -> tuple[str, bool]:
    """Drop a trailing incomplete sentence; keep earlier complete sentences."""
    stripped = (text or "").rstrip()
    if not stripped:
        return text, False

    trailing_cites = ""
    cite_match = _TRAILING_CITATIONS_RE.search(stripped)
    if cite_match:
        trailing_cites = cite_match.group(0)
        body = stripped[: cite_match.start()].rstrip()
    else:
        body = stripped

    if not body or _SENTENCE_END_RE.search(body):
        return text, False

    for idx in range(len(body) - 1, -1, -1):
        if body[idx] in ".!?;":
            trimmed = body[: idx + 1].rstrip()
            if trimmed:
                return trimmed + trailing_cites, True
    return text, False


def finalize_answer_text(text: str, *, truncated: bool = False) -> tuple[str, bool]:
    if not text:
        return text, False
    if truncated or looks_incomplete_answer(text):
        return trim_to_last_complete_sentence(text)
    return text, False
