from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import chromadb

KNOWLEDGE_DIR = Path("data/knowledge")
VECTOR_DIR = Path("aria_vectors")

# Initialize ChromaDB persistent client using default embeddings
_client = chromadb.PersistentClient(path=str(VECTOR_DIR))
_collection = _client.get_or_create_collection(name="aria_knowledge")


def sync_file_to_vector_db(file_path: str) -> bool:
    """Read a saved JSON knowledge file and upsert its content into ChromaDB."""
    try:
        path = Path(file_path)
        if not path.exists():
            return False

        with open(path, "r", encoding="utf-8") as f:
            record: Dict[str, Any] = json.load(f)

        category = record.get("category", "general")
        data_payload = record.get("data", {})
        
        # Build text string for embedding
        doc_text = f"Category: {category} | Summary: {json.dumps(data_payload)}"
        doc_id = f"{category}_{path.stem}"

        _collection.upsert(
            documents=[doc_text],
            metadatas=[{"category": category, "source": str(path)}],
            ids=[doc_id]
        )
        return True
    except Exception as e:
        print(f"[VectorEmbedder Error]: {e}")
        return False
