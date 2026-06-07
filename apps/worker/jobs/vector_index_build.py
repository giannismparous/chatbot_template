from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from dotenv import load_dotenv

from packages.adapters.llm.gemini_adapter import GeminiAdapter
from packages.adapters.retrieval.embedding_utils import deterministic_embed

load_dotenv()

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB_PATH = ROOT / "packages" / "config" / "defaults" / "chatbot.sqlite3"
VECTOR_INDEX_PATH = ROOT / "packages" / "config" / "defaults" / "vector_index.json"


def _build_embeddings(texts: List[str]) -> tuple[List[List[float]], str]:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    embedding_model = os.getenv("EMBEDDING_MODEL", "gemini-embedding-001")
    if not api_key:
        return [deterministic_embed(t) for t in texts], "deterministic_fallback_no_key"
    try:
        adapter = GeminiAdapter(api_key=api_key)
        vectors = adapter.embed_texts(texts=texts, model=embedding_model)
        # If API returned empty embeddings, fail over safely.
        if not vectors or any(len(v) == 0 for v in vectors):
            return [deterministic_embed(t) for t in texts], "deterministic_fallback_empty_gemini"
        return vectors, f"gemini:{embedding_model}"
    except Exception as exc:
        print(f"Gemini embedding failed. Falling back to deterministic embeddings. Error: {exc}")
        return [deterministic_embed(t) for t in texts], "deterministic_fallback_error"


def run_vector_index_build() -> int:
    db_path = Path(os.getenv("DB_SQLITE_PATH", "")).expanduser() if os.getenv("DB_SQLITE_PATH") else DEFAULT_DB_PATH
    if not db_path.exists():
        print(f"DB not found at {db_path}. Run build_index first.")
        return 0

    with sqlite3.connect(str(db_path)) as conn:
        rows = conn.execute(
            """
            SELECT id, COALESCE(title,''), content, COALESCE(source_url,''), COALESCE(language,'en')
            FROM knowledge_chunks
            """
        ).fetchall()

    raw_docs = []
    texts: List[str] = []
    for row in rows:
        row_id, title, content, source_url, language = row
        text = f"{title}\n{content}".strip()
        raw_docs.append(
            {"id": row_id, "title": title, "content": content, "source_url": source_url, "language": language}
        )
        texts.append(text)

    vectors, embedding_provider = _build_embeddings(texts)
    docs = []
    for d, vec in zip(raw_docs, vectors):
        doc = dict(d)
        doc["embedding"] = vec
        docs.append(doc)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "embedding_provider": embedding_provider,
        "documents": docs,
    }
    VECTOR_INDEX_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    qdrant_url = os.getenv("QDRANT_URL", "").strip()
    if qdrant_url:
        try:
            from packages.adapters.vectorstore.qdrant_adapter import QdrantAdapter

            qdrant = QdrantAdapter(
                url=qdrant_url,
                api_key=os.getenv("QDRANT_API_KEY", "").strip() or None,
                collection=os.getenv("QDRANT_COLLECTION", "chatbot_chunks"),
                vector_size=len(docs[0]["embedding"]) if docs else 128,
            )
            qdrant.upsert(docs)
            print(f"Qdrant upsert complete. Upserted vectors: {len(docs)}")
        except Exception as exc:
            print(f"Qdrant upsert skipped due to error: {exc}")

    print(f"Vector index build complete. Indexed vectors: {len(docs)} (provider={embedding_provider})")
    return len(docs)


if __name__ == "__main__":
    run_vector_index_build()
