"""Version and authorization boundary for the public RAG knowledge corpus."""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

KNOWLEDGE_ROOT = Path(__file__).resolve().parents[2] / "knowledge"


@lru_cache(maxsize=8)
def _version_for(root: str) -> str:
    """Stable content version used to expire stale retrieval and prompt caches."""
    digest = hashlib.sha256()
    knowledge_root = Path(root)
    if knowledge_root.is_dir():
        for path in sorted(knowledge_root.rglob("*.md")):
            relative = path.relative_to(knowledge_root).as_posix()
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
    return digest.hexdigest()[:20]


def knowledge_corpus_version(root: Path | None = None) -> str:
    return _version_for(str((root or KNOWLEDGE_ROOT).resolve()))


@lru_cache(maxsize=8)
def _current_sources(root: str) -> frozenset[str]:
    knowledge_root = Path(root)
    if not knowledge_root.is_dir():
        return frozenset()
    return frozenset(
        path.relative_to(knowledge_root).as_posix()
        for path in knowledge_root.rglob("*.md")
    )


def authorize_knowledge_chunks(
    chunks,
    *,
    actor_role: str | None = None,
    permissions: frozenset[str] | None = None,
):
    """Keep only current product docs whose audience is authorized.

    RAG points with unknown/tenant-owned sources are rejected. Content bearing
    tenant identifiers is never treated as public knowledge.
    """
    allowed: list = []
    for chunk in chunks:
        metadata = chunk.metadata or {}
        source = metadata.get("source", "")
        if source not in _current_sources(str(KNOWLEDGE_ROOT.resolve())):
            continue
        if metadata.get("corpus_version") != knowledge_corpus_version():
            continue
        if any(
            key.casefold()
            in {"tenantid", "tenant_id", "storeid", "store_id", "userid", "user_id"}
            for key in metadata
        ):
            continue
        audience = _csv_values(metadata.get("audience"))
        public_audiences = {"public", "all", "authenticated", "signed_in"}
        if audience and not audience.intersection(public_audiences):
            if not actor_role or not audience.intersection({actor_role.casefold()}):
                continue
        roles = _csv_values(metadata.get("roles") or metadata.get("audience_roles"))
        if roles and (not actor_role or actor_role.casefold() not in roles):
            continue
        required = _csv_values(
            metadata.get("permissions") or metadata.get("required_permissions")
        )
        if required and (permissions is None or not required.issubset(permissions)):
            continue
        allowed.append(chunk)
    return allowed


def _csv_values(raw: str | None) -> set[str]:
    if not raw:
        return set()
    return {value.strip().casefold() for value in raw.split(",") if value.strip()}
