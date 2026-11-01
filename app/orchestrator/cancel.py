"""Cooperative cancel flag for chat/stream requests."""

from __future__ import annotations

import asyncio


class CancelScope:
    __slots__ = ("_event",)

    def __init__(self) -> None:
        self._event = asyncio.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            raise asyncio.CancelledError()
