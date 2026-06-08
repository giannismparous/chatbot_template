from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from apps.api.dependencies.stack import get_stack
from packages.adapters.config.tenant_prompt_policy import TenantPromptPolicyEngine
from packages.adapters.config.tenant_theme_provider import TenantThemeProvider
from packages.adapters.connectors.api_connector import APIConnector
from packages.adapters.connectors.db_connector import DBConnector
from packages.adapters.connectors.google_drive_connector import GoogleDriveConnector
from packages.adapters.connectors.tenant_local_files_connector import TenantLocalFilesConnector
from packages.adapters.retrieval.tenant_retriever_v2 import TenantRetrieverV2
from packages.adapters.llm.gemini_adapter import GeminiLLMBackend
from packages.adapters.llm.resilient_provider import ResilientLLMProvider
from packages.adapters.retrieval.hybrid_adapter import HybridFederatedRetriever
from packages.adapters.retrieval.mode_router import ModeRouterRetriever
from packages.adapters.retrieval.vector_index_adapter import VectorIndexRetriever
from packages.core.config.loader import TenantConfigLoader
from packages.core.llm.key_pool import LLMKeyPool
from packages.core.llm.orchestrator import LLMOrchestrator
from packages.core.orchestrator.chat_orchestrator import ChatOrchestrator
from packages.core.stack.factory import project_root

load_dotenv()

ROOT = project_root()
# Legacy shared defaults — admin MVP + retrieval until Phase 3/11
CLIENTS_PATH = str(ROOT / "packages" / "config" / "defaults" / "clients.yaml")
PROMPT_POLICY_PATH = str(ROOT / "packages" / "config" / "defaults" / "prompt_policy.yaml")
THEME_PATH = str(ROOT / "packages" / "config" / "defaults" / "themes.yaml")
# Legacy shared defaults — retrieval/index MVP until Phase 3 per-client indexes
KNOWLEDGE_PATH = str(ROOT / "packages" / "config" / "defaults" / "knowledge.json")
GOOGLE_DRIVE_INDEX_PATH = str(ROOT / "packages" / "config" / "defaults" / "google_drive_index.json")
DB_SQLITE_PATH = os.getenv("DB_SQLITE_PATH", str(ROOT / "packages" / "config" / "defaults" / "chatbot.sqlite3"))
if not DB_SQLITE_PATH.strip():
    DB_SQLITE_PATH = str(ROOT / "packages" / "config" / "defaults" / "chatbot.sqlite3")
VECTOR_INDEX_PATH = str(ROOT / "packages" / "config" / "defaults" / "vector_index.json")
API_SOURCES_PATH = str(ROOT / "packages" / "config" / "defaults" / "api_sources.yaml")
QDRANT_URL = os.getenv("QDRANT_URL", "").strip()
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "").strip()
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "chatbot_chunks")


def build_tenant_config_loader() -> TenantConfigLoader:
    stack = get_stack()
    return TenantConfigLoader(
        clients_root=stack.config_store.get_clients_root(),
        domain_packs_root=ROOT / "packages" / "domain_packs",
    )


def build_orchestrator(config_loader: TenantConfigLoader) -> ChatOrchestrator:
    default_client = os.getenv("DEFAULT_CLIENT_ID", "default")
    stack = get_stack()
    if stack.profile == "firebase":
        from packages.core.storage.api_runtime_hydrator import prepare_firebase_api_runtime_index

        index_report = prepare_firebase_api_runtime_index(client_id=default_client, stack=stack)
        index_report.emit()
    else:
        from packages.core.storage.tenant_cache_hydrator import hydrate_client_config

        hydrate_client_config(
            client_id=default_client,
            file_store=stack.file_store,
            config_meta_store=stack.config_meta_store,
        )
    merged = config_loader.load(default_client)
    source_weights = merged.client.get("source_weights") or {}
    clients_root = stack.config_store.get_clients_root()

    connectors = {
        "local_files": TenantLocalFilesConnector(
            clients_root=clients_root,
            legacy_fallback_path=KNOWLEDGE_PATH,
        ),
        "google_drive": GoogleDriveConnector(GOOGLE_DRIVE_INDEX_PATH),
        "api": APIConnector(
            base_url=os.getenv("API_CONNECTOR_BASE_URL", "").strip(),
            config_path=API_SOURCES_PATH,
            api_key=os.getenv("API_CONNECTOR_API_KEY", "").strip(),
            client_id=default_client,
        ),
        "db": DBConnector(DB_SQLITE_PATH),
    }
    hybrid_retriever = HybridFederatedRetriever(connectors=connectors, source_weights=source_weights)
    tenant_retriever_v2 = TenantRetrieverV2.build_default(
        clients_root=clients_root,
        config_loader=config_loader,
        legacy_fallback_path=KNOWLEDGE_PATH,
    )
    vector_retriever = VectorIndexRetriever(VECTOR_INDEX_PATH)
    vector_mode_retriever = vector_retriever
    if QDRANT_URL:
        try:
            from packages.adapters.retrieval.qdrant_retriever import QdrantRetriever
            from packages.adapters.vectorstore.qdrant_adapter import QdrantAdapter

            qdrant = QdrantAdapter(
                url=QDRANT_URL,
                api_key=QDRANT_API_KEY or None,
                collection=QDRANT_COLLECTION,
            )
            vector_mode_retriever = QdrantRetriever(qdrant)
        except Exception:
            vector_mode_retriever = vector_retriever
    retriever = ModeRouterRetriever(
        retrievers_by_mode={
            "hybrid_local": tenant_retriever_v2,
            "drive_hybrid": hybrid_retriever,
            "vector_db": vector_mode_retriever,
        },
        fallback_mode="hybrid_local",
    )
    policy = TenantPromptPolicyEngine(config_loader)
    default_model = os.getenv("DEFAULT_MODEL", "gemini-2.5-flash-lite")
    merged_llm = merged.llm or {}
    key_cfg = merged_llm.get("key_pool") or {}
    key_pool = LLMKeyPool.from_env(
        cooldown_seconds=float(key_cfg.get("cooldown_seconds", 60)),
        env_list_var=str(key_cfg.get("env_list_var") or "GEMINI_API_KEYS"),
        env_primary_var=str(key_cfg.get("env_primary_var") or "GEMINI_API_KEY"),
    )
    llm_orchestrator = LLMOrchestrator(
        backend=GeminiLLMBackend(),
        key_pool=key_pool,
        stack_profile=stack.profile,
        default_model_env=default_model,
    )
    llm = ResilientLLMProvider(llm_orchestrator)
    return ChatOrchestrator(
        llm_provider=llm,
        retriever=retriever,
        prompt_policy=policy,
        config_loader=config_loader,
        default_model=default_model,
        stack_profile=stack.profile,
        trace_store=stack.trace_store,
        metrics_store=stack.metrics_store,
    )


def build_theme_provider(config_loader: TenantConfigLoader) -> TenantThemeProvider:
    return TenantThemeProvider(config_loader)


TENANT_CONFIG = build_tenant_config_loader()
ORCHESTRATOR = build_orchestrator(TENANT_CONFIG)
THEMES = build_theme_provider(TENANT_CONFIG)


def reload_runtime() -> None:
    global TENANT_CONFIG, ORCHESTRATOR, THEMES
    TENANT_CONFIG = build_tenant_config_loader()
    TENANT_CONFIG.clear_cache()
    ORCHESTRATOR = build_orchestrator(TENANT_CONFIG)
    THEMES = build_theme_provider(TENANT_CONFIG)


def get_public_client_config(client_id: str) -> dict:
    merged = TENANT_CONFIG.load(client_id)
    client = merged.client
    return {
        "client_id": merged.client_id,
        "display_name": client.get("display_name"),
        "domain_pack": merged.domain_pack,
        "modes": client.get("modes", []),
        "default_mode": client.get("default_mode", "hybrid_local"),
        "source_weights": client.get("source_weights", {}),
        "regulated_mode": client.get("regulated_mode", False),
        "suggested_questions": client.get("suggested_questions", []),
    }
