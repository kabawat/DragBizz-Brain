from __future__ import annotations

import hashlib
import re
import uuid

from pydantic import BaseModel

CHUNK_MAX_TOKENS = 700
CHUNK_OVERLAP_TOKENS = 85

_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
_HEADING_RE = re.compile(r"^(#{1,2})\s+(.*)$", re.MULTILINE)


class DocumentChunk(BaseModel):
    id: str
    content: str
    metadata: dict[str, str]


def chunk_markdown(text: str, *, source: str) -> list[DocumentChunk]:
    """Split a markdown document into embedding-ready chunks.

    Sections (## headings) are packed greedily up to CHUNK_MAX_TOKENS;
    oversized sections are split on paragraphs with token overlap.
    """
    metadata, body = _parse_frontmatter(text)
    metadata["source"] = source

    title, sections = _split_sections(body)
    if title:
        metadata["title"] = title

    chunks: list[DocumentChunk] = []
    for heading, section_text in _pack_sections(sections):
        for part in _split_oversized(section_text):
            content = _compose_content(title, heading, part)
            chunk_metadata = dict(metadata)
            if heading:
                chunk_metadata["heading"] = heading
            chunks.append(
                DocumentChunk(
                    id=_chunk_id(source, content),
                    content=content,
                    metadata=chunk_metadata,
                )
            )
    return chunks


def estimate_tokens(text: str) -> int:
    # Conservative ~4 chars/token heuristic; docs stay far below model limits.
    return max(1, len(text) // 4)


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text

    metadata: dict[str, str] = {}
    for line in match.group(1).splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip():
            metadata[key.strip()] = value.strip()
    return metadata, text[match.end() :]


def _split_sections(body: str) -> tuple[str, list[tuple[str, str]]]:
    """Return (document title, [(heading, section text), ...])."""
    title = ""
    sections: list[tuple[str, str]] = []
    current_heading = ""
    cursor = 0

    matches = list(_HEADING_RE.finditer(body))
    for index, match in enumerate(matches):
        leading = body[cursor : match.start()].strip()
        if leading:
            sections.append((current_heading, leading))

        if match.group(1) == "#" and not title:
            title = match.group(2).strip()
            current_heading = ""
        else:
            current_heading = match.group(2).strip()

        cursor = match.end()
        is_last = index == len(matches) - 1
        if is_last:
            trailing = body[cursor:].strip()
            if trailing:
                sections.append((current_heading, trailing))

    if not matches:
        stripped = body.strip()
        if stripped:
            sections.append(("", stripped))
    return title, sections


def _pack_sections(
    sections: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    """Greedily merge consecutive sections while staying under the limit."""
    packed: list[tuple[str, str]] = []
    for heading, text in sections:
        if packed:
            previous_heading, previous_text = packed[-1]
            merged = f"{previous_text}\n\n## {heading}\n\n{text}" if heading else (
                f"{previous_text}\n\n{text}"
            )
            if estimate_tokens(merged) <= CHUNK_MAX_TOKENS:
                packed[-1] = (previous_heading, merged)
                continue
        packed.append((heading, text))
    return packed


def _split_oversized(text: str) -> list[str]:
    if estimate_tokens(text) <= CHUNK_MAX_TOKENS:
        return [text]

    paragraphs = [p for p in re.split(r"\n\n+", text) if p.strip()]
    parts: list[str] = []
    current: list[str] = []
    current_tokens = 0

    for paragraph in paragraphs:
        paragraph_tokens = estimate_tokens(paragraph)
        if current and current_tokens + paragraph_tokens > CHUNK_MAX_TOKENS:
            parts.append("\n\n".join(current))
            current = _overlap_tail(current)
            current_tokens = sum(estimate_tokens(p) for p in current)
        current.append(paragraph)
        current_tokens += paragraph_tokens

    if current:
        parts.append("\n\n".join(current))
    return parts


def _overlap_tail(paragraphs: list[str]) -> list[str]:
    """Keep trailing paragraphs worth ~CHUNK_OVERLAP_TOKENS as overlap."""
    tail: list[str] = []
    tokens = 0
    for paragraph in reversed(paragraphs):
        paragraph_tokens = estimate_tokens(paragraph)
        if tokens + paragraph_tokens > CHUNK_OVERLAP_TOKENS:
            break
        tail.insert(0, paragraph)
        tokens += paragraph_tokens
    return tail


def _compose_content(title: str, heading: str, text: str) -> str:
    context = " — ".join(part for part in (title, heading) if part)
    return f"{context}\n\n{text}" if context else text


def _chunk_id(source: str, content: str) -> str:
    digest = hashlib.sha256(f"{source}\n{content}".encode()).digest()
    return str(uuid.UUID(bytes=digest[:16]))
