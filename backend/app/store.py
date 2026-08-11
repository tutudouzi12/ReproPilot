from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from .models import PlanEvent, PlanGraph, utc_now


class PlanNotFound(KeyError):
    pass


class FilePlanStore:
    """Small JSON store with serialized updates and atomic file replacement."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = asyncio.Lock()
        self._plans: dict[str, PlanGraph] = {}
        self._events: dict[str, list[PlanEvent]] = {}

    async def load(self) -> None:
        if not self.path.exists():
            return
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self._plans = {
            key: PlanGraph.model_validate(value)
            for key, value in data.get("plans", {}).items()
        }
        self._events = {
            key: [PlanEvent.model_validate(item) for item in values]
            for key, values in data.get("events", {}).items()
        }
        await self.recover_interrupted()

    async def recover_interrupted(self) -> None:
        changed = False
        for plan in self._plans.values():
            for node in plan.nodes:
                if node.status == "in_progress":
                    node.status = "pending"
                    node.error = "recovered after backend restart"
                    node.execution_id = None
                    node.lease_owner = None
                    node.lease_expires_at = None
                    changed = True
            if plan.status == "in_progress":
                plan.status = "pending"
                changed = True
            plan.refresh_meta()
        if changed:
            await self._persist()

    async def save_plan(self, plan: PlanGraph) -> None:
        async with self._lock:
            plan.refresh_meta()
            # Keep the store isolated from mutations made by schedulers or API
            # callers after save_plan returns.
            self._plans[plan.id] = plan.model_copy(deep=True)
            self._events.setdefault(plan.id, [])
            await self._persist()

    async def get_plan(self, plan_id: str) -> PlanGraph:
        plan = self._plans.get(plan_id)
        if plan is None:
            raise PlanNotFound(plan_id)
        return plan.model_copy(deep=True)

    async def append_event(self, event: PlanEvent) -> None:
        async with self._lock:
            if event.plan_id not in self._plans:
                raise PlanNotFound(event.plan_id)
            self._events.setdefault(event.plan_id, []).append(event.model_copy(deep=True))
            await self._persist()

    async def list_events(self, plan_id: str) -> list[PlanEvent]:
        if plan_id not in self._plans:
            raise PlanNotFound(plan_id)
        return [event.model_copy(deep=True) for event in self._events.get(plan_id, [])]

    async def _persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "plans": {
                key: value.model_dump(mode="json", by_alias=True)
                for key, value in self._plans.items()
            },
            "events": {
                key: [event.model_dump(mode="json") for event in values]
                for key, values in self._events.items()
            },
            "updated_at": utc_now().isoformat(),
        }
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            os.chmod(temp, 0o600)
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, self.path)
        # Directory fsync is available on POSIX. Windows' os.replace already
        # provides the atomic name swap, but directories cannot be opened this
        # way there.
        if hasattr(os, "O_DIRECTORY"):
            directory_fd = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
