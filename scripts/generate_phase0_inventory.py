"""Generate the Phase 0 inventory from the runtime tool registry."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

from app.rag.chunker import chunk_markdown
from app.tools.registry import build_unified_tool_registry

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "phase0"


def retailer_calls(handler_path: Path, handler_name: str) -> list[str]:
    """Return RetailerClient methods directly referenced by a tool handler."""
    tree = ast.parse(handler_path.read_text(encoding="utf-8"))
    function = next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == handler_name
        ),
        None,
    )
    if function is None:
        return []
    calls = {
        node.attr
        for node in ast.walk(function)
        if isinstance(node, ast.Attribute)
        and node.attr
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "retailer"
    }
    return sorted(calls)


def build_inventory() -> list[dict[str, object]]:
    registry = build_unified_tool_registry()
    inventory = []
    for entry in registry.entries():
        handler = entry.handler
        source = Path(handler.__code__.co_filename).resolve()
        inventory.append(
            {
                "name": entry.name,
                "domain": entry.domain.value,
                "access": entry.access_type.value,
                "risk": entry.definition.risk.value,
                "registered_at_startup": True,
                "handler": f"{source.relative_to(ROOT)}:{handler.__name__}",
                "retailer_client_methods": retailer_calls(source, handler.__name__),
                "requires_confirmation": entry.requires_confirmation,
                "required_permissions": list(entry.required_permissions),
                "allows_parallel": entry.definition.allows_parallel,
                "description": entry.definition.description,
                "input_schema": entry.definition.parameters,
                "effective_user_authorization": "runtime permission dependent",
                "execution_verified_by_inventory": False,
            }
        )
    return inventory


def render_markdown(inventory: list[dict[str, object]]) -> str:
    counts: dict[str, int] = {}
    for item in inventory:
        domain = str(item["domain"])
        counts[domain] = counts.get(domain, 0) + 1

    lines = [
        "# Phase 0 Capability Inventory",
        "",
        "> Generated from `app.tools.registry.build_unified_tool_registry()` by "
        "`scripts/generate_phase0_inventory.py`. This records what is registered "
        "at startup; it does not prove that a user's permissions allow a call or "
        "that the downstream operation succeeds.",
        "",
        f"**Registered tools:** {len(inventory)}",
        "**Domains:** "
        + ", ".join(f"{domain}: {count}" for domain, count in sorted(counts.items())),
        "",
        "## Runtime tool catalogue",
        "",
        "| Tool | Domain | Access / risk | Confirmation | Required permission | "
        "Handler | Retailer methods |",
        "|---|---|---|---:|---|---|---|",
    ]
    for item in inventory:
        methods = ", ".join(item["retailer_client_methods"]) or "none detected"
        permission = ", ".join(item["required_permissions"]) or "none declared"
        lines.append(
            "| `{name}` | {domain} | {access} / {risk} | {confirm} | "
            "{permission} | `{handler}` | {methods} |".format(
                name=item["name"],
                domain=item["domain"],
                access=item["access"],
                risk=item["risk"],
                confirm="yes" if item["requires_confirmation"] else "no",
                permission=permission,
                handler=item["handler"],
                methods=methods,
            )
        )
    lines.extend(
        [
            "",
            "## Interpretation and limits",
            "",
            "- Registration means a definition and handler are wired by the "
            "startup registry. It does not prove routing, permission, downstream "
            "availability, or end-to-end success.",
            "- `effective_user_authorization` is deliberately not inferred here; "
            "it depends on the authenticated caller and runtime policy.",
            "- Retailer methods are extracted from direct handler references. "
            "Indirect calls and external RAG/UI capabilities may need manual mapping.",
            "- Analytics tools remain listed because they exist in the registry, "
            "but analytics feature testing is outside this phase's scope.",
            "- Regenerate after tool registry/handler changes and review the diff:",
            "  `source .venv/bin/activate && "
            "python scripts/generate_phase0_inventory.py`",
            "",
        ]
    )
    return "\n".join(lines)


def build_knowledge_inventory() -> list[dict[str, object]]:
    knowledge_root = ROOT / "knowledge"
    result = []
    for path in sorted(knowledge_root.rglob("*.md")):
        content = path.read_bytes()
        relative = path.relative_to(knowledge_root).as_posix()
        chunks = chunk_markdown(content.decode("utf-8"), source=relative)
        result.append(
            {
                "source": relative,
                "sha256": hashlib.sha256(content).hexdigest(),
                "bytes": len(content),
                "chunk_count": len(chunks),
                "scope": "global product documentation; no tenant records in corpus",
                "execution_verified": False,
            }
        )
    return result


def write_inventory() -> list[dict[str, object]]:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    inventory = build_inventory()
    (OUTPUT / "capability_inventory.json").write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (OUTPUT / "capability_inventory.md").write_text(
        render_markdown(inventory), encoding="utf-8"
    )
    knowledge = build_knowledge_inventory()
    (OUTPUT / "knowledge_inventory.json").write_text(
        json.dumps(knowledge, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return inventory


if __name__ == "__main__":
    result = write_inventory()
    print(
        f"Generated inventory for {len(result)} registered tools and "
        f"{len(build_knowledge_inventory())} knowledge files at {OUTPUT}"
    )
