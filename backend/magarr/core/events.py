"""Tiny in-process pub/sub: background work tells WebSocket clients that something changed."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[str]] = set()

    def publish(self, topic: str) -> None:
        for queue in list(self._subscribers):
            if queue.qsize() < 100:  # a stuck client must not grow memory forever
                queue.put_nowait(topic)

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[str]]:
        queue: asyncio.Queue[str] = asyncio.Queue()
        self._subscribers.add(queue)
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)
