from __future__ import annotations

from packages.core.chat.answer_completeness import (
    finalize_answer_text,
    looks_incomplete_answer,
    trim_to_last_complete_sentence,
)


def test_looks_incomplete_detects_mid_word_cutoff() -> None:
    assert looks_incomplete_answer("Το σύστημα είναι σχεδιασμένο ώστε να μην επινοεί π")
    assert not looks_incomplete_answer("Το σύστημα είναι σχεδιασμένο ώστε να μην επινοεί πηγές [1].")


def test_trim_to_last_complete_sentence() -> None:
    text = (
        "Η simasiaAI δημιουργεί chatbots [1]. "
        "Ένα παράδειγμα είναι το MYRTO [2]. "
        "Η simasiaAI δίνει"
    )
    trimmed, changed = trim_to_last_complete_sentence(text)
    assert changed
    assert trimmed.endswith("[2].")
    assert "Η simasiaAI δίνει" not in trimmed


def test_finalize_keeps_complete_answers() -> None:
    answer = "Πλήρης πρόταση με τελεία."
    result, changed = finalize_answer_text(answer, truncated=False)
    assert result == answer
    assert changed is False


def test_finalize_trims_when_truncated_flag_set() -> None:
    answer = "Πρώτη πρόταση. Δεύτερη ημιτελής λέ"
    result, changed = finalize_answer_text(answer, truncated=True)
    assert changed
    assert result == "Πρώτη πρόταση."
