"""
RAG Retrieval Tool — Wraps ChromaDB MMR search as a LangChain @tool.

This tool lets ReAct agents autonomously query the factory troubleshooting
manual for relevant safety rules, repair procedures, and parameter bounds.
"""

import logging
from langchain_core.tools import tool

from core.rag_retriever import Chroma, embedding_model, CHROMA_DB_DIR

logger = logging.getLogger(__name__)


@tool
def search_factory_manual(query: str) -> str:
    """Search the factory troubleshooting manual for relevant guidelines,
    safety rules, and repair procedures.

    Uses MMR (Maximal Marginal Relevance) semantic search over the
    ChromaDB knowledge base to find diverse, relevant content.

    Args:
        query: Natural language description of what you're looking for.
               Examples: "motor temperature exceeds 70C",
                         "belt speed safe operating range",
                         "gripper vacuum pressure limits"

    Returns:
        Concatenated text of the top 3 most relevant manual sections,
        or a message indicating no results were found.
    """
    try:
        vectorstore = Chroma(
            persist_directory=CHROMA_DB_DIR,
            embedding_function=embedding_model,
        )
        retriever = vectorstore.as_retriever(
            search_type="mmr",
            search_kwargs={"k": 3, "fetch_k": 10, "lambda_mult": 0.8},
        )
        docs = retriever.invoke(query)
        if docs:
            result = "\n\n---\n\n".join([doc.page_content for doc in docs])
            logger.info(f"RAG returned {len(docs)} docs for query: {query[:60]}...")
            return result
        return "No relevant factory manual guidelines found for this query."
    except Exception as e:
        logger.error(f"RAG retrieval failed: {e}")
        return f"RAG retrieval error: {str(e)}"
