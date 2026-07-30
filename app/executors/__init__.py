"""Tool runtime boundary: risk policy + execute_reads/writes/confirmations.

Kept separate from app/tools/ (definitions + handlers). Growth stays inside
this package (policy/audit splits) — not a second parallel executor domain.
"""

from app.executors.tool_executor import ToolExecutor

__all__ = ["ToolExecutor"]
