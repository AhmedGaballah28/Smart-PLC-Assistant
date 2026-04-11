"""
Build Knowledge Base
Seeds ChromaDB with fault knowledge from fault_knowledge.json.

Usage:
    python knowledge_base/build_kb.py
"""

import os
os.environ["OPENBLAS_NUM_THREADS"] = "1"
import sys
import json
import logging
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s │ %(levelname)s │ %(message)s")
logger = logging.getLogger("BuildKB")

FAULT_KNOWLEDGE_FILE = Path(__file__).parent / "fault_knowledge.json"
DB_PATH = str(PROJECT_ROOT / "data" / "chroma_db")


def build():
    logger.info("Building knowledge base...")

    # Load fault knowledge
    if not FAULT_KNOWLEDGE_FILE.exists():
        logger.error(f"fault_knowledge.json not found at {FAULT_KNOWLEDGE_FILE}")
        sys.exit(1)

    with open(FAULT_KNOWLEDGE_FILE, "r", encoding="utf-8") as f:
        knowledge = json.load(f)

    logger.info(f"Loaded {len(knowledge)} knowledge entries")

    # Connect to ChromaDB
    try:
        import chromadb
        import chromadb.utils.embedding_functions as embedding_functions
        
        api_key = os.getenv("GOOGLE_API_KEY", "")
        if not api_key:
            env_file = PROJECT_ROOT / ".env"
            if env_file.exists():
                for line in env_file.read_text().splitlines():
                    if line.startswith("GOOGLE_API_KEY="):
                        api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
        
        gemini_ef = embedding_functions.GoogleGenerativeAiEmbeddingFunction(api_key=api_key)

        (PROJECT_ROOT / "data" / "chroma_db").mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(path=DB_PATH)
        # Delete and recreate for a clean build
        try:
            client.delete_collection("fault_knowledge")
        except Exception:
            pass
        collection = client.create_collection(
            name="fault_knowledge",
            metadata={"hnsw:space": "cosine"},
            embedding_function=gemini_ef
        )
    except ImportError:
        logger.error("chromadb not installed. Run: pip install chromadb")
        sys.exit(1)
    except Exception as e:
        logger.error(f"ChromaDB error: {e}")
        sys.exit(1)

    # Insert documents in batches
    batch_size = 50
    ids, docs, metas = [], [], []

    for i, entry in enumerate(knowledge):
        doc_id = entry.get("id", str(i))
        title = entry.get("title", "")
        content = entry.get("content", "")
        metadata = {
            "title": title,
            "station": entry.get("station", "all"),
            "fault_type": entry.get("fault_type", "general"),
            "category": entry.get("category", "general"),
        }
        # Build rich text for embedding
        text = f"Title: {title}\n\n{content}"
        ids.append(doc_id)
        docs.append(text)
        metas.append(metadata)

        if len(ids) >= batch_size:
            collection.add(ids=ids, documents=docs, metadatas=metas)
            logger.info(f"  Inserted batch up to entry {i + 1}")
            ids, docs, metas = [], [], []

    if ids:
        collection.add(ids=ids, documents=docs, metadatas=metas)

    total = collection.count()
    logger.info(f"✅ Knowledge base built — {total} documents ready")

    # Quick test
    results = collection.query(query_texts=["overheat belt motor station 1"], n_results=2)
    logger.info(f"Test query returned {len(results['documents'][0])} results:")
    for doc in results["documents"][0]:
        logger.info(f"  → {doc[:80]}...")


if __name__ == "__main__":
    build()
