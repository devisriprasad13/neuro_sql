"""
RAG (Retrieval-Augmented Generation) package.

Provides schema embedding and retrieval for SQL generation.

Usage:
    from app.core.rag import SchemaEmbedder, SchemaRetriever
"""

from app.core.rag.schema_embedder import SchemaEmbedder, build_embedding_text
from app.core.rag.schema_retriever import SchemaRetriever

__all__ = [
    "SchemaEmbedder",
    "SchemaRetriever",
    "build_embedding_text",
]