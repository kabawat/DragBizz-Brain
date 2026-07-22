"""RAG infrastructure (vector store first; chunk/embed/retrieve later)."""

from app.rag.vector_store import VectorStore

__all__ = ["VectorStore"]
