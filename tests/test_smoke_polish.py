from __future__ import annotations

from pathlib import Path

import json

import pytest

from packages.core.config.loader import TenantConfigLoader
from packages.core.eval.assertions import evaluate_retrieval
from packages.core.eval.loader import load_eval_cases
from packages.core.retrieval.faq import match_faq_entries
from packages.core.retrieval.pipeline import TenantRetrievalPipeline

ROOT = Path(__file__).resolve().parents[1]
PACKS = ROOT / "packages" / "domain_packs"
CLIENTS = ROOT / "data" / "clients"


@pytest.fixture(scope="module")
def default_pipeline() -> TenantRetrievalPipeline:
    loader = TenantConfigLoader(clients_root=CLIENTS, domain_packs_root=PACKS)
    return TenantRetrievalPipeline(
        clients_root=CLIENTS,
        config_loader=loader,
        legacy_fallback_path=ROOT / "packages" / "config" / "defaults" / "knowledge.json",
    )


def test_myrto_query_retrieves_context(default_pipeline: TenantRetrievalPipeline) -> None:
    outcome = default_pipeline.retrieve("Τι είναι το MYRTO;", client_id="default", limit=6)
    assert outcome.no_context is False
    combined = " ".join(c.text for c in outcome.chunks).lower()
    assert "myrto" in combined


def test_myrto_eval_case_defined() -> None:
    cases = load_eval_cases(CLIENTS, "default")
    myrto = next(c for c in cases if c.id == "smoke_myrto_retrieval")
    results = evaluate_retrieval(
        myrto.expect,
        TenantRetrievalPipeline(
            clients_root=CLIENTS,
            config_loader=TenantConfigLoader(clients_root=CLIENTS, domain_packs_root=PACKS),
            legacy_fallback_path=ROOT / "packages" / "config" / "defaults" / "knowledge.json",
        ).retrieve("Τι είναι το MYRTO;", client_id="default", limit=6),
    )
    assert all(r.passed for r in results)


def test_aade_eval_case_present() -> None:
    cases = load_eval_cases(CLIENTS, "default")
    aade = next(c for c in cases if c.id == "smoke_aade_acronym")
    assert "ακρωνύμ" in aade.expect.expected_contains
    assert "ΑΔΑΕ" in aade.expect.expected_not_contains


def test_privacy_eval_case_retrieval(default_pipeline: TenantRetrievalPipeline) -> None:
    cases = load_eval_cases(CLIENTS, "default")
    privacy = next(c for c in cases if c.id == "smoke_privacy_retrieval")
    outcome = default_pipeline.retrieve("Αποθηκεύετε προσωπικά δεδομένα;", client_id="default", limit=6)
    results = evaluate_retrieval(privacy.expect, outcome)
    assert all(r.passed for r in results)
    combined = " ".join(c.text for c in outcome.chunks).lower()
    assert "pii" in combined or "anonymized" in combined or "ανώνυμ" in combined


def test_poamskp_contact_faq_triggers() -> None:
    faq_config = json.loads((CLIENTS / "default" / "config" / "faq.json").read_text(encoding="utf-8"))
    query = "Πώς μπορώ να επικοινωνήσω με την ΠΟΑμΣΚΠ;"
    chunks, scores = match_faq_entries(query, faq_config)
    assert any(c.id == "faq-poamskp-contact" for c in chunks)
    contact = next(c for c in chunks if c.id == "faq-poamskp-contact")
    assert "213" in contact.content
    assert "poamskp@otenet.gr" in contact.content
    assert scores["faq-poamskp-contact"].is_faq is True


@pytest.mark.parametrize(
    "query",
    [
        "Πώς μπορώ να επικοινωνήσω με την ΠΟΑμΣΚΠ;",
        "Ποια είναι η διεύθυνση της ΠΟΑμΣΚΠ;",
        "Τηλέφωνο επικοινωνίας ΠΟΑμΣΚΠ",
        "POAMSKP contact email",
    ],
)
def test_poamskp_contact_faq_trigger_variants(query: str) -> None:
    faq_config = json.loads((CLIENTS / "default" / "config" / "faq.json").read_text(encoding="utf-8"))
    chunks, _ = match_faq_entries(query, faq_config)
    assert any(c.id == "faq-poamskp-contact" for c in chunks)


def test_poamskp_contact_eval_case_retrieval(default_pipeline: TenantRetrievalPipeline) -> None:
    cases = load_eval_cases(CLIENTS, "default")
    contact = next(c for c in cases if c.id == "smoke_poamskp_contact_retrieval")
    outcome = default_pipeline.retrieve(
        "Πώς μπορώ να επικοινωνήσω με την ΠΟΑμΣΚΠ;",
        client_id="default",
        limit=6,
    )
    results = evaluate_retrieval(contact.expect, outcome)
    assert all(r.passed for r in results)
    combined = " ".join(c.text for c in outcome.chunks).lower()
    assert "213" in combined
    assert "poamskp" in combined


def test_poamskp_contact_eval_case_defined() -> None:
    cases = load_eval_cases(CLIENTS, "default")
    answer = next(c for c in cases if c.id == "smoke_poamskp_contact_answer")
    assert "213" in answer.expect.expected_contains
    assert "poamskp" in answer.expect.expected_contains
    assert "could not find" in answer.expect.expected_not_contains
