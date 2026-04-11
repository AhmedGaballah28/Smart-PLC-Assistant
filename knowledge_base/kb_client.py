"""
Knowledge Base Client
Queries ChromaDB for fault-relevant documents.
Falls back gracefully if ChromaDB is not built yet.
"""

import logging
import os
os.environ["OPENBLAS_NUM_THREADS"] = "1"
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

DB_PATH = str(Path(__file__).resolve().parents[1] / "data" / "chroma_db")
COLLECTION_NAME = "fault_knowledge"


class KnowledgeBaseClient:
    """
    ChromaDB-backed knowledge base for fault diagnosis RAG.
    
    Usage:
        kb = KnowledgeBaseClient()
        results = kb.search("belt motor overheat station 1", n_results=3)
    """

    def __init__(self, db_path: str = DB_PATH):
        self._client = None
        self._collection = None
        self._available = False

        try:
            import chromadb
            import chromadb.utils.embedding_functions as embedding_functions
            from chromadb.config import Settings
            
            api_key = os.getenv("GOOGLE_API_KEY", "")
            if not api_key:
                env_file = Path(__file__).resolve().parents[1] / ".env"
                if env_file.exists():
                    for line in env_file.read_text().splitlines():
                        if line.startswith("GOOGLE_API_KEY="):
                            api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                            break
            
            gemini_ef = embedding_functions.GoogleGenerativeAiEmbeddingFunction(api_key=api_key)

            self._client = chromadb.PersistentClient(path=db_path)
            self._collection = self._client.get_or_create_collection(
                name=COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},
                embedding_function=gemini_ef
            )
            count = self._collection.count()
            self._available = count > 0
            if self._available:
                logger.info(f"✅ Knowledge base ready — {count} documents")
            else:
                logger.warning("⚠️  Knowledge base is empty. Run: python knowledge_base/build_kb.py")
        except ImportError:
            logger.warning("chromadb not installed — KB unavailable")
        except Exception as e:
            logger.warning(f"KB init error: {e}")

    def is_available(self) -> bool:
        return self._available

    def search(self, query: str, n_results: int = 3) -> List[Dict]:
        """Search for relevant fault documents."""
        if not self._available or self._collection is None:
            return []
        try:
            results = self._collection.query(
                query_texts=[query],
                n_results=min(n_results, self._collection.count()),
                include=["documents", "metadatas", "distances"],
            )
            output = []
            docs = results.get("documents", [[]])[0]
            metas = results.get("metadatas", [[]])[0]
            dists = results.get("distances", [[]])[0]
            for doc, meta, dist in zip(docs, metas, dists):
                output.append({
                    "document": doc,
                    "metadata": meta,
                    "relevance_score": round(1.0 - dist, 3),
                })
            return output
        except Exception as e:
            logger.error(f"KB search error: {e}")
            return []

    def add_document(self, doc_id: str, text: str, metadata: dict = None):
        """Add a single document to the KB."""
        if self._collection is None:
            return False
        try:
            self._collection.add(
                ids=[doc_id],
                documents=[text],
                metadatas=[metadata or {}],
            )
            self._available = True
            return True
        except Exception as e:
            logger.error(f"KB add error: {e}")
            return False

    def get_count(self) -> int:
        if self._collection is None:
            return 0
        try:
            return self._collection.count()
        except Exception:
            return 0
