from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import List

from packages.core.domain.interfaces import KnowledgeConnector
from packages.core.domain.models import RetrievedChunk


class DBConnector(KnowledgeConnector):
    def __init__(self, sqlite_path: str) -> None:
        self._sqlite_path = Path(sqlite_path)
        self._sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with sqlite3.connect(str(self._sqlite_path)) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_chunks (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    content TEXT NOT NULL,
                    source_url TEXT,
                    language TEXT DEFAULT 'en',
                    metadata_json TEXT DEFAULT '{}'
                )
                """
            )
            conn.commit()

    def search(self, query: str, limit: int = 10, **kwargs: Any) -> List[RetrievedChunk]:
        tokens = [t.strip().lower() for t in query.split() if t.strip()]
        if not tokens:
            return []

        like_clause = " OR ".join(["LOWER(title) LIKE ? OR LOWER(content) LIKE ?" for _ in tokens])
        params: List[str] = []
        for token in tokens:
            like = f"%{token}%"
            params.extend([like, like])
        params.append(str(max(1, limit * 3)))

        sql = f"""
        SELECT id, COALESCE(title, ''), content, COALESCE(source_url, ''), COALESCE(language, 'en')
        FROM knowledge_chunks
        WHERE {like_clause}
        LIMIT ?
        """
        rows = []
        with sqlite3.connect(str(self._sqlite_path)) as conn:
            rows = conn.execute(sql, params).fetchall()

        scored: List[RetrievedChunk] = []
        for row in rows:
            row_id, title, content, source_url, language = row
            hay = f"{title}\n{content}".lower()
            hit_count = sum(1 for tok in tokens if tok in hay)
            if hit_count <= 0:
                continue
            scored.append(
                RetrievedChunk(
                    id=row_id,
                    text=f"{title}\n{content}".strip(),
                    source=source_url or "db://knowledge_chunks",
                    score=float(hit_count) / max(1, len(tokens)),
                    metadata={"connector": "db", "language": language, "title": title},
                )
            )
        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[:limit]
