from __future__ import annotations

import asyncio
from collections import defaultdict

from .models import PlanEvent
from .store import FilePlanStore


class EventBus:
    def __init__(self, store: FilePlanStore) -> None:
        self.store = store
        self._subscribers: dict[str, set[asyncio.Queue[PlanEvent]]] = defaultdict(set)

    async def publish(self, event: PlanEvent) -> None:
        await self.store.append_event(event)
        for queue in tuple(self._subscribers[event.plan_id]):
            await queue.put(event)

    def subscribe(self, plan_id: str) -> asyncio.Queue[PlanEvent]:
        queue: asyncio.Queue[PlanEvent] = asyncio.Queue(maxsize=100)
        self._subscribers[plan_id].add(queue)
        return queue

    def unsubscribe(self, plan_id: str, queue: asyncio.Queue[PlanEvent]) -> None:
        self._subscribers[plan_id].discard(queue)
        if not self._subscribers[plan_id]:
            self._subscribers.pop(plan_id, None)

