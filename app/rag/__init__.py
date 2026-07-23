"""RAG infrastructure (vector store, chunking, embeddings, indexing; retrieval later).

The indexer is a CLI entrypoint (`python -m app.rag.indexer`), imported directly.
"""

from app.rag.chunker import DocumentChunk, chunk_markdown
from app.rag.embedding_service import EmbeddingService
from app.rag.retriever import RetrievedChunk, Retriever
from app.rag.vector_store import VectorStore

__all__ = [
    "DocumentChunk",
    "EmbeddingService",
    "RetrievedChunk",
    "Retriever",
    "VectorStore",
    "chunk_markdown",
]
