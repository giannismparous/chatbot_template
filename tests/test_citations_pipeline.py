from __future__ import annotations

from pathlib import Path

from packages.core.citations.context_builder import build_citation_context, format_numbered_context
from packages.core.citations.enforcer import enforce_citations
from packages.core.citations.models import CitationContext, CitedChunk
from packages.core.config.loader import TenantConfigLoader
from packages.core.domain.models import ChatRequest, PublicSource, RetrievedChunk
from packages.core.orchestrator.chat_orchestrator import ChatOrchestrator
from packages.core.retrieval.models import RetrievalOutcome

ROOT = Path(__file__).resolve().parents[1]
PACKS = ROOT / "packages" / "domain_packs"


def _chunk(
    *,
    chunk_id: str = "c1",
    title: str = "Doc",
    content: str = "body",
    internal_url: str = "uploads/private.txt",
    citation_url: str | None = None,
    source_visibility: str = "internal",
    is_faq: bool = False,
    score: float = 0.9,
) -> RetrievedChunk:
    return RetrievedChunk(
        id=chunk_id,
        text=f"{title}\n{content}",
        source=internal_url,
        score=score,
        metadata={
            "title": title,
            "internal_url": internal_url,
            "citation_url": citation_url,
            "source_visibility": source_visibility,
            "is_faq": is_faq,
        },
    )


def _context(*chunks: RetrievedChunk) -> CitationContext:
    return build_citation_context(list(chunks))


def _whitelist(
    *,
    domains: list[str] | None = None,
    allow_only: bool = True,
    include_only_cited: bool = True,
) -> dict:
    return {
        "allowed_public_domains": domains or [],
        "citation_url_rules": {
            "strip_llm_urls": True,
            "allow_only_whitelisted": allow_only,
        },
        "citation_enforcement": {
            "include_only_cited_sources": include_only_cited,
            "require_citation_markers": False,
        },
    }


def test_context_builder_numbers_chunks_correctly() -> None:
    ctx = _context(_chunk(chunk_id="a"), _chunk(chunk_id="b", title="Second"))
    assert [c.index for c in ctx.chunks] == [1, 2]
    assert ctx.index_by_id["a"] == 1


def test_context_builder_prefers_public_mapped_sources_first() -> None:
    ctx = _context(
        _chunk(
            chunk_id="faq-1",
            internal_url="faq://faq-overview",
            is_faq=True,
            source_visibility="internal",
            score=3.0,
        ),
        _chunk(
            chunk_id="public-1",
            citation_url="https://simasiaai.gr/",
            source_visibility="public",
            score=0.5,
        ),
    )
    assert ctx.chunks[0].chunk_id == "public-1"
    assert ctx.chunks[0].index == 1
    assert ctx.chunks[1].chunk_id == "faq-1"
    assert ctx.chunks[1].index == 2


def test_context_does_not_expose_internal_paths() -> None:
    ctx = _context(_chunk(internal_url="uploads/secret.txt"))
    text = format_numbered_context(ctx)
    assert "uploads/secret.txt" not in text
    assert "[1] Title: Doc" in text


def test_valid_marker_preserved_invalid_stripped() -> None:
    ctx = _context(
        _chunk(
            citation_url="https://client.com/hours",
            source_visibility="public",
        )
    )
    result = enforce_citations(
        "Support hours are 9-5 [1] and fake [99].",
        ctx,
        _whitelist(domains=["client.com"], allow_only=True),
    )
    assert "[1]" in result.answer
    assert "[99]" not in result.answer
    assert 99 in result.stripped_citations


def test_invented_url_stripped() -> None:
    ctx = _context(
        _chunk(
            citation_url="https://client.com/hours",
            source_visibility="public",
        )
    )
    whitelist = _whitelist(domains=["client.com"])
    result = enforce_citations(
        "See https://evil.example/fake and https://client.com/hours for details [1].",
        ctx,
        whitelist,
    )
    assert "https://evil.example/fake" not in result.answer
    assert "https://client.com/hours" in result.answer
    assert "https://evil.example/fake" in result.stripped_urls


def test_whitelisted_retrieved_url_preserved_without_citation_marker() -> None:
    ctx = _context(
        _chunk(
            citation_url="https://client.com/page",
            source_visibility="public",
        )
    )
    result = enforce_citations("Read https://client.com/page for more.", ctx, _whitelist(domains=["client.com"]))
    assert "https://client.com/page" in result.answer


def test_internal_upload_never_in_public_sources() -> None:
    ctx = _context(_chunk(internal_url="uploads/handbook.pdf"))
    result = enforce_citations("See handbook [1].", ctx, _whitelist(domains=["client.com"]))
    assert result.public_sources == []
    assert "[1]" not in result.answer


def test_faq_internal_hidden_from_public_sources() -> None:
    ctx = _context(
        _chunk(
            chunk_id="faq-1",
            internal_url="faq://faq-hours",
            is_faq=True,
            source_visibility="internal",
        )
    )
    result = enforce_citations("Hours are 9-5 [1].", ctx, _whitelist(domains=["client.com"]))
    assert result.public_sources == []
    assert "[1]" not in result.answer
    assert "Hours are 9-5" in result.answer


def test_public_faq_source_requires_whitelist_and_citation() -> None:
    ctx = _context(
        _chunk(
            chunk_id="faq-public",
            title="FAQ Hours",
            internal_url="faq://faq-hours",
            citation_url="https://client.com/faq-hours",
            source_visibility="public",
            is_faq=True,
        )
    )
    whitelist = _whitelist(domains=["client.com"])

    cited = enforce_citations("Open hours are listed [1].", ctx, whitelist)
    assert len(cited.public_sources) == 1
    assert cited.public_sources[0].url == "https://client.com/faq-hours"

    uncited = enforce_citations("Open hours are listed.", ctx, whitelist)
    assert uncited.public_sources == []

    not_whitelisted = enforce_citations("Open hours are listed [1].", ctx, _whitelist(domains=["other.com"]))
    assert not_whitelisted.public_sources == []


def test_grouped_citation_markers_count_toward_public_sources() -> None:
    ctx = _context(
        _chunk(
            chunk_id="c1",
            citation_url="https://simasiaai.gr/",
            source_visibility="public",
        ),
        _chunk(
            chunk_id="c2",
            title="Collaborations",
            citation_url="https://simasiaai.gr/collaborations",
            source_visibility="public",
            score=0.8,
        ),
    )
    whitelist = _whitelist(domains=["simasiaai.gr"], include_only_cited=True)
    result = enforce_citations("Details in [1, 2].", ctx, whitelist)
    urls = {source.url for source in result.public_sources}
    assert urls == {"https://simasiaai.gr/", "https://simasiaai.gr/collaborations"}
    assert result.answer == "Details in [1, 2]."


def _ctx_public_at_1_internal_faq_at_5() -> CitationContext:
    return CitationContext(
        chunks=[
            CitedChunk(
                index=1,
                chunk_id="public-1",
                title="Landing",
                content="landing body",
                internal_url="uploads/landing.md",
                citation_url="https://simasiaai.gr/",
                source_visibility="public",
                is_faq=False,
                score=0.9,
            ),
            CitedChunk(
                index=5,
                chunk_id="faq-1",
                title="FAQ overview",
                content="faq body",
                internal_url="faq://overview",
                citation_url=None,
                source_visibility="internal",
                is_faq=True,
                score=2.5,
            ),
        ],
        index_by_id={"public-1": 1, "faq-1": 5},
    )


def test_public_answer_strips_internal_citation_markers() -> None:
    ctx = _ctx_public_at_1_internal_faq_at_5()
    whitelist = _whitelist(domains=["simasiaai.gr"], include_only_cited=True)
    result = enforce_citations(
        "Overview [1] with FAQ [5] and grouped [1, 5] plus pair [2, 5].",
        ctx,
        whitelist,
    )
    assert len(result.public_sources) == 1
    assert result.public_sources[0].index == 1
    assert result.public_sources[0].url == "https://simasiaai.gr/"
    assert "[5]" not in result.answer
    assert "[1, 5]" not in result.answer
    assert "[2, 5]" not in result.answer
    assert result.answer == "Overview [1] with FAQ and grouped [1] plus pair."
    assert result.valid_citations == {1}
    assert 5 in result.stripped_citations


def test_grouped_markers_drop_hidden_indices() -> None:
    ctx = _ctx_public_at_1_internal_faq_at_5()
    whitelist = _whitelist(domains=["simasiaai.gr"], include_only_cited=True)
    result = enforce_citations("Claim [1, 5].", ctx, whitelist)
    assert result.answer == "Claim [1]."
    assert result.public_sources[0].index == 1


def test_public_sources_deduped_by_url() -> None:
    ctx = _context(
        _chunk(
            chunk_id="c1",
            citation_url="https://simasiaai.gr/",
            source_visibility="public",
        ),
        _chunk(
            chunk_id="c2",
            title="Second",
            citation_url="https://simasiaai.gr/",
            source_visibility="public",
            score=0.8,
        ),
    )
    whitelist = _whitelist(domains=["simasiaai.gr"], include_only_cited=True)
    result = enforce_citations("Both sources cited [1] and [2].", ctx, whitelist)
    assert len(result.public_sources) == 1
    assert result.public_sources[0].url == "https://simasiaai.gr/"
    assert result.public_sources[0].index == 1


def test_include_only_cited_excludes_uncited_public_chunks() -> None:
    ctx = _context(
        _chunk(
            chunk_id="c1",
            citation_url="https://client.com/a",
            source_visibility="public",
        ),
        _chunk(
            chunk_id="c2",
            title="Second",
            citation_url="https://client.com/b",
            source_visibility="public",
            score=0.8,
        ),
    )
    whitelist = _whitelist(domains=["client.com"], include_only_cited=True)
    result = enforce_citations("Only first source [1].", ctx, whitelist)
    assert len(result.public_sources) == 1
    assert result.public_sources[0].index == 1


def test_empty_whitelist_blocks_public_sources() -> None:
    ctx = _context(
        _chunk(
            citation_url="https://client.com/public",
            source_visibility="public",
        )
    )
    result = enforce_citations("Details [1].", ctx, _whitelist(domains=[], allow_only=True))
    assert result.public_sources == []


def test_allow_only_false_permits_public_sources_without_domain_list() -> None:
    ctx = _context(
        _chunk(
            citation_url="https://client.com/public",
            source_visibility="public",
        )
    )
    result = enforce_citations("Details [1].", ctx, _whitelist(domains=[], allow_only=False))
    assert len(result.public_sources) == 1


class _MockLLM:
    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.called = False

    def generate(self, system_prompt, messages, model, temperature=0.2) -> str:
        self.called = True
        return self.answer


class _MockPolicy:
    def build_system_prompt(self, client_id: str, mode: str) -> str:
        return "system"


class _NoContextRetriever:
    def retrieve_with_outcome(self, query, limit=5, mode="hybrid_local", **kwargs):
        return RetrievalOutcome(
            chunks=[],
            no_context=True,
            no_context_message="No relevant sources.",
        )


def test_no_context_still_skips_llm(tmp_path) -> None:
    clients_root = tmp_path / "clients"
    config_dir = clients_root / "tenant_a" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "client.yaml").write_text(
        "client_id: tenant_a\ndisplay_name: Tenant A\ndomain_pack: generic\n",
        encoding="utf-8",
    )

    llm = _MockLLM("should not run")
    loader = TenantConfigLoader(clients_root=clients_root, domain_packs_root=PACKS)
    orchestrator = ChatOrchestrator(
        llm_provider=llm,
        retriever=_NoContextRetriever(),
        prompt_policy=_MockPolicy(),
        default_model="test",
        config_loader=loader,
    )
    res = orchestrator.answer(ChatRequest(client_id="tenant_a", message="hello", top_k=3))
    assert res.answer == "No relevant sources."
    assert res.sources == []
    assert res.escalation is not None
    assert res.escalation.type == "dont_know"
    assert llm.called is False


def test_orchestrator_returns_public_sources_only(tmp_path) -> None:
    clients_root = tmp_path / "clients"
    config_dir = clients_root / "tenant_a" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "client.yaml").write_text(
        "client_id: tenant_a\ndisplay_name: Tenant A\ndomain_pack: generic\n",
        encoding="utf-8",
    )
    (config_dir / "source_whitelist.yaml").write_text(
        "allowed_public_domains:\n  - client.com\n",
        encoding="utf-8",
    )

    class _Retriever:
        def retrieve_with_outcome(self, query, limit=5, mode="hybrid_local", **kwargs):
            return RetrievalOutcome(
                chunks=[
                    _chunk(
                        citation_url="https://client.com/doc",
                        source_visibility="public",
                    )
                ],
                no_context=False,
            )

    llm = _MockLLM("Answer text [1].")
    loader = TenantConfigLoader(clients_root=clients_root, domain_packs_root=PACKS)
    orchestrator = ChatOrchestrator(
        llm_provider=llm,
        retriever=_Retriever(),
        prompt_policy=_MockPolicy(),
        default_model="test",
        config_loader=loader,
    )
    res = orchestrator.answer(ChatRequest(client_id="tenant_a", message="hello", top_k=3))
    assert llm.called is True
    assert len(res.sources) == 1
    source = res.sources[0]
    assert isinstance(source, PublicSource)
    assert source.url == "https://client.com/doc"
    assert source.index == 1
