from __future__ import annotations

import re

from app.schemas.chat import GenerationResponse

_DASHBOARD_LINK_RE = re.compile(
    r"(?:https?://)?[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?::\d+)?"
    r"(/dashboard/[^\s)\]\"']*)"
)


def normalize_dashboard_links(text: str) -> str:
    return _DASHBOARD_LINK_RE.sub(r"\1", text)


def sum_optional_tokens(*values: int | None) -> int | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return sum(present)


def get_usage_source(generations: list[GenerationResponse]) -> str:
    if not generations:
        return "estimated"
    if all(
        item.input_tokens is not None and item.output_tokens is not None
        for item in generations
    ):
        return "actual"
    return "estimated"
