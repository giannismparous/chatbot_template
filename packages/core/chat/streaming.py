from __future__ import annotations

import json
from typing import Any, Iterator


FORBIDDEN_STREAM_KEYS = frozenset(
    {
        "trace",
        "retrieval",
        "llm",
        "prompt",
        "chunks",
        "score",
        "internal",
        "block_reason",
        "attempts",
    }
)


def chunk_text(text: str, *, chunk_size: int = 24) -> list[str]:
    if not text:
        return []
    parts: list[str] = []
    i = 0
    while i < len(text):
        parts.append(text[i : i + chunk_size])
        i += chunk_size
    return parts


def format_sse_event(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def stream_buffered_answer(
    *,
    answer: str,
    done_payload: dict[str, Any],
    emit_chunks: bool,
) -> Iterator[str]:
    if emit_chunks:
        for piece in chunk_text(answer):
            yield format_sse_event("chunk", {"text": piece})
    yield format_sse_event("done", done_payload)


def assert_safe_done_payload(payload: dict[str, Any]) -> None:
    for key in payload:
        if key in FORBIDDEN_STREAM_KEYS:
            raise ValueError(f"Forbidden stream field: {key}")
    for src in payload.get("sources") or []:
        if isinstance(src, dict) and "score" in src:
            raise ValueError("sources must not include score in stream payload")
