from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB_PATH = ROOT / "packages" / "config" / "defaults" / "chatbot.sqlite3"
DEFAULT_KNOWLEDGE_PATH = ROOT / "packages" / "config" / "defaults" / "knowledge.json"
DEFAULT_DRIVE_INDEX_PATH = ROOT / "packages" / "config" / "defaults" / "google_drive_index.json"


def _ensure_schema(conn: sqlite3.Connection) -> None:
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


def _load_json(path: Path) -> list[dict]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        return payload.get("documents", [])
    if isinstance(payload, list):
        return payload
    return []


def run_db_seed() -> int:
    db_path = Path(os.getenv("DB_SQLITE_PATH", "")).expanduser() if os.getenv("DB_SQLITE_PATH") else DEFAULT_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)

    local_docs = _load_json(DEFAULT_KNOWLEDGE_PATH)
    drive_docs = _load_json(DEFAULT_DRIVE_INDEX_PATH)
    all_docs = [*local_docs, *drive_docs]

    inserted = 0
    with sqlite3.connect(str(db_path)) as conn:
        _ensure_schema(conn)
        for d in all_docs:
            row_id = str(d.get("id", "")).strip()
            content = str(d.get("content", "")).strip()
            if not row_id or not content:
                continue
            title = str(d.get("title", ""))
            source_url = str(d.get("url", d.get("source", "")))
            language = str(d.get("language", "en"))
            metadata_json = json.dumps(
                {"seeded_from": d.get("source", "local"), "file_id": d.get("file_id", "")},
                ensure_ascii=False,
            )
            conn.execute(
                """
                INSERT INTO knowledge_chunks (id, title, content, source_url, language, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,
                    content=excluded.content,
                    source_url=excluded.source_url,
                    language=excluded.language,
                    metadata_json=excluded.metadata_json
                """,
                (row_id, title, content, source_url, language, metadata_json),
            )
            inserted += 1
        conn.commit()

    print(f"DB seed complete. Upserted chunks: {inserted}. DB: {db_path}")
    return inserted


if __name__ == "__main__":
    run_db_seed()
