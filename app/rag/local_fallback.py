"""Keyword fallback over knowledge/*.md when vector RAG is unavailable."""

from __future__ import annotations

import re
from pathlib import Path

from app.rag.corpus import knowledge_corpus_version
from app.rag.models import RetrievedChunk

DEFAULT_KNOWLEDGE_ROOT = Path(__file__).resolve().parents[2] / "knowledge"

_FRONTMATTER_RE = re.compile(r"^---\s*\n.*?\n---\s*\n", re.DOTALL)
_TOKEN_RE = re.compile(r"[a-z0-9]{3,}", re.IGNORECASE)
_STOP = frozenset(
    {
        "the",
        "and",
        "for",
        "how",
        "do",
        "does",
        "what",
        "when",
        "where",
        "who",
        "why",
        "can",
        "you",
        "please",
        "with",
        "from",
        "this",
        "that",
        "have",
        "has",
        "are",
        "was",
        "were",
        "will",
        "into",
        "about",
        "using",
        "use",
        "used",
    }
)


def _tokens(text: str) -> set[str]:
    return {token for token in _TOKEN_RE.findall(text.lower()) if token not in _STOP}


def _strip_frontmatter(raw: str) -> str:
    return _FRONTMATTER_RE.sub("", raw, count=1).strip()


def retrieve_local_knowledge(
    question: str,
    *,
    root: Path | None = None,
    limit: int = 3,
) -> list[RetrievedChunk]:
    """Score markdown docs by keyword overlap; no embeddings required."""
    knowledge_root = root or DEFAULT_KNOWLEDGE_ROOT
    if not knowledge_root.is_dir():
        return []

    query_tokens = _tokens(question)
    if not query_tokens:
        return []

    scored: list[tuple[float, Path, str]] = []
    for path in knowledge_root.rglob("*.md"):
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            continue
        body = _strip_frontmatter(raw)
        if not body:
            continue
        doc_tokens = _tokens(f"{path.stem} {path.parent.name} {body[:4000]}")
        overlap = query_tokens & doc_tokens
        if not overlap:
            continue
        # Prefer denser overlap relative to query size.
        score = len(overlap) / max(len(query_tokens), 1)
        # Slight boost when path names match (voice-assistant, invoice, …).
        path_bits = _tokens(f"{path.stem} {path.parent.name}")
        score += 0.15 * len(query_tokens & path_bits)
        scored.append((score, path, body))

    scored.sort(key=lambda item: item[0], reverse=True)
    chunks: list[RetrievedChunk] = []
    for score, path, body in scored[:limit]:
        relative = path.relative_to(knowledge_root).as_posix()
        chunks.append(
            RetrievedChunk(
                id=f"local:{relative}",
                text=body[:3500],
                metadata={
                    "source": relative,
                    "fallback": "local",
                    "corpus_version": knowledge_corpus_version(),
                },
                score=round(score, 4),
            )
        )
    return chunks
