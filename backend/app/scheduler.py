from __future__ import annotations

import asyncio
from datetime import timedelta
from uuid import uuid4

from .agents import RoutedAgentExecutor
from .events import EventBus
from .models import PlanEvent, PlanGraph, TaskNode, utc_now
from .store import FilePlanStore


TERMINAL_TASK_STATUSES = {"completed", "failed", "blocked", "skipped", "canceled"}
FAILED_DEPENDENCY_STATUSES = {"failed", "blocked", "canceled"}


def infer_artifact_type(key: str) -> str:
    lowered = key.lower()
    if lowered in {"claim_rubric", "claim_evidence_graph"} or "assessment" in lowered:
        return "json"
    if "plot" in lowered or "image" in lowered:
        return "image_base64"
    if "code" in lowered:
        return "code"
    if "url" in lowered:
        return "url"
    if any(token in lowered for token in ("path", "env", "workspace", "runtime")):
        return "text"
    if "metrics" in lowered:
        return "metrics"
    if "report" in lowered:
        return "report"
    if "dependency" in lowered:
        return "dependency_spec"
    return "text"


def build_artifact(
    key: str,
    producer_task_id: str,
    value,
    *,
    result="",
    code="",
    structured_data="",
) -> dict:
    return {
        "key": key,
        "type": infer_artifact_type(key),
        "producer_task_id": producer_task_id,
        # Keep task_id for compatibility with the existing frontend/API shape.
        "task_id": producer_task_id,
        "value": value,
        "result": result,
        "code": code,
        "structured_data": structured_data,
        "created_at": utc_now().isoformat(),
    }


class SchedulerConflict(RuntimeError):
    pass


class DAGScheduler:
    def __init__(
        self,
        store: FilePlanStore,
        events: EventBus,
        executor: RoutedAgentExecutor,
        max_concurrent: int = 2,
    ) -> None:
        self.store = store
        self.events = events
        self.executor = executor
        self.max_concurrent = max(1, max_concurrent)
        self._runs: dict[str, asyncio.Task[None]] = {}

    def start(self, plan_id: str) -> None:
        current = self._runs.get(plan_id)
        if current and not current.done():
            raise SchedulerConflict("plan is already running")
        task = asyncio.create_task(self.execute_plan(plan_id), name=f"plan-{plan_id}")
        self._runs[plan_id] = task
        task.add_done_callback(lambda _: self._runs.pop(plan_id, None))

    async def cancel(self, plan_id: str) -> None:
        plan = await self.store.get_plan(plan_id)
        if plan.status in {"completed", "failed", "canceled"}:
            raise SchedulerConflict(f"terminal plan cannot be canceled from {plan.status}")
        running = self._runs.get(plan_id)
        for node in plan.nodes:
            if node.status not in TERMINAL_TASK_STATUSES:
                node.status = "canceled"
                node.error = "canceled by user"
                node.finished_at = utc_now()
                node.execution_epoch += 1
                node.execution_id = None
                node.lease_owner = None
                node.lease_expires_at = None
        plan.status = "canceled"
        plan.usage.finished_at = utc_now()
        await self.store.save_plan(plan)
        await self.events.publish(PlanEvent(plan_id=plan.id, event_type="plan_canceled", task_status="canceled", trace_id=plan.trace_id))
        if running and not running.done():
            running.cancel()
        else:
            await self._cleanup_terminal_runtime(plan)

    async def retry_task(self, plan_id: str, task_id: str) -> None:
        plan = await self.store.get_plan(plan_id)
        task = self._find_task(plan, task_id)
        if task.status not in {"failed", "blocked", "canceled"}:
            raise SchedulerConflict(f"task cannot be retried from status {task.status}")
        task.status = "pending"
        task.error = None
        task.finished_at = None
        task.execution_id = None
        reset_ids = {task.id}
        changed = True
        while changed:
            changed = False
            for dependent in plan.nodes:
                if dependent.id in reset_ids or dependent.status != "blocked":
                    continue
                if any(dependency in reset_ids for dependency in dependent.dependencies):
                    dependent.status = "pending"
                    dependent.error = None
                    dependent.finished_at = None
                    reset_ids.add(dependent.id)
                    changed = True
        plan.status = "pending"
        await self.store.save_plan(plan)
        await self.events.publish(PlanEvent(plan_id=plan.id, event_type="task_retry_requested", task_id=task.id, task_status="pending", trace_id=plan.trace_id))

    async def reassign_task(self, plan_id: str, task_id: str, assigned_to: str) -> None:
        assigned_to = assigned_to.strip()
        if not assigned_to:
            raise SchedulerConflict("assigned_to is required")
        plan = await self.store.get_plan(plan_id)
        if plan.status in {"completed", "failed", "canceled"}:
            raise SchedulerConflict(f"terminal plan cannot be changed from {plan.status}")
        task = self._find_task(plan, task_id)
        previous = task.assigned_to
        task.assigned_to = assigned_to
        task.status = "pending"
        task.error = None
        task.result = None
        task.finished_at = None
        task.execution_epoch += 1
        task.execution_id = None
        task.lease_owner = None
        task.lease_expires_at = None
        await self.store.save_plan(plan)
        await self.events.publish(PlanEvent(
            plan_id=plan.id,
            event_type="task_reassigned",
            task_id=task.id,
            task_status="pending",
            trace_id=plan.trace_id,
            payload={"from": previous, "to": assigned_to},
        ))

    async def execute_plan(self, plan_id: str) -> None:
        plan = await self.store.get_plan(plan_id)
        plan.status = "in_progress"
        plan.usage.started_at = plan.usage.started_at or utc_now()
        await self.store.save_plan(plan)
        await self.events.publish(PlanEvent(plan_id=plan.id, event_type="plan_started", task_status="in_progress", trace_id=plan.trace_id))

        try:
            while True:
                if self._duration_budget_exhausted(plan):
                    await self._cancel_for_budget(plan, "plan duration budget exhausted")
                    return
                newly_blocked = self._block_failed_dependencies(plan)
                previously_ready = {node.id for node in plan.nodes if node.status == "ready"}
                ready = self._promote_ready(plan)
                newly_ready = [node for node in ready if node.id not in previously_ready]
                if newly_blocked or newly_ready:
                    await self.store.save_plan(plan)
                for node, upstream_id in newly_blocked:
                    await self.events.publish(PlanEvent(
                        plan_id=plan.id,
                        event_type="task_blocked",
                        task_id=node.id,
                        task_status=node.status,
                        trace_id=plan.trace_id,
                        payload={"upstream_task_id": upstream_id, "error": node.error},
                    ))
                for node in newly_ready:
                    await self.events.publish(PlanEvent(
                        plan_id=plan.id,
                        event_type="task_ready",
                        task_id=node.id,
                        task_status=node.status,
                        trace_id=plan.trace_id,
                        payload={"inputs": node.inputs, "required_artifacts": node.required_artifacts},
                    ))
                active = [node for node in plan.nodes if node.status == "in_progress"]
                unfinished = [node for node in plan.nodes if node.status not in TERMINAL_TASK_STATUSES]
                if not unfinished:
                    break
                if not ready and not active:
                    for node in unfinished:
                        node.status = "blocked"
                        node.error = "dependency graph cannot make progress"
                    break

                remaining_attempts = plan.budget.max_task_attempts - plan.usage.task_attempts
                if remaining_attempts <= 0:
                    await self._cancel_for_budget(plan, "task attempt budget exhausted")
                    return
                batch = sorted(ready, key=lambda item: (-item.priority, item.created_at))[
                    : min(self.max_concurrent, remaining_attempts)
                ]
                if batch:
                    await self.store.save_plan(plan)
                    await asyncio.gather(*(self._run_task(plan, node) for node in batch))

            failed = any(node.status in {"failed", "blocked"} for node in plan.nodes)
            plan.status = "failed" if failed else "completed"
            plan.usage.finished_at = utc_now()
            await self.store.save_plan(plan)
            terminal_error = next(
                (node.error for node in plan.nodes if node.status == "failed" and node.error),
                None,
            )
            await self.events.publish(PlanEvent(
                plan_id=plan.id,
                event_type="plan_failed" if failed else "plan_completed",
                task_status=plan.status,
                trace_id=plan.trace_id,
                payload={"error": terminal_error or "plan contains failed or blocked tasks"} if failed else {},
            ))
        except asyncio.CancelledError:
            persisted = await self.store.get_plan(plan.id)
            if persisted.status == "canceled":
                # An API cancellation has already invalidated execution leases
                # in durable state. Never overwrite that state with this run's
                # stale in-memory task snapshot.
                plan = persisted
            else:
                for node in plan.nodes:
                    if node.status not in TERMINAL_TASK_STATUSES:
                        node.status = "canceled"
                        node.error = "scheduler execution was canceled"
                        node.execution_epoch += 1
                        node.execution_id = None
                        node.lease_owner = None
                        node.lease_expires_at = None
                        node.finished_at = utc_now()
                plan.status = "canceled"
                plan.usage.finished_at = utc_now()
                await self.store.save_plan(plan)
            raise
        finally:
            if plan.status in {"completed", "failed", "canceled"}:
                try:
                    await asyncio.shield(self._cleanup_terminal_runtime(plan))
                except asyncio.CancelledError:
                    pass

    async def _run_task(self, plan: PlanGraph, task: TaskNode) -> None:
        for artifact_name in task.output_artifacts:
            existing = plan.artifacts.get(artifact_name)
            if isinstance(existing, dict) and existing.get("producer_task_id") == task.id:
                plan.artifacts.pop(artifact_name, None)
        task.status = "in_progress"
        task.run_count += 1
        task.execution_epoch += 1
        task.execution_id = uuid4().hex
        execution_id = task.execution_id
        execution_epoch = task.execution_epoch
        lease_owner = f"scheduler-{uuid4().hex}"
        task.lease_owner = lease_owner
        task.lease_expires_at = utc_now() + timedelta(seconds=task.timeout_seconds)
        task.started_at = utc_now()
        task.updated_at = utc_now()
        plan.usage.task_attempts += 1
        await self.store.save_plan(plan)
        await self.events.publish(PlanEvent(
            plan_id=plan.id,
            event_type="task_started",
            task_id=task.id,
            task_status=task.status,
            trace_id=plan.trace_id,
            execution_id=task.execution_id,
        ))
        task_snapshot = task.model_copy(deep=True)
        plan_snapshot = plan.model_copy(deep=True)
        plan_remaining = self._remaining_duration(plan)
        effective_timeout = max(0.001, min(float(task.timeout_seconds), plan_remaining))
        execution_logs: list[str] = []
        created_artifact_keys: list[str] = []
        try:
            result = await asyncio.wait_for(
                self.executor.execute(task_snapshot, plan_snapshot),
                timeout=effective_timeout,
            )
            execution_logs = result.logs
            # Re-read the lease from durable state. API-driven reassignment uses
            # a separate plan copy, so checking only this run's in-memory graph
            # would allow the old agent result to overwrite the handoff.
            persisted = await self.store.get_plan(plan.id)
            current = self._find_task(persisted, task.id)
            if (
                current.execution_id != execution_id
                or current.execution_epoch != execution_epoch
                or current.lease_owner != lease_owner
            ):
                for index, candidate in enumerate(plan.nodes):
                    if candidate.id == task.id:
                        plan.nodes[index] = current
                        break
                await self.events.publish(PlanEvent(
                    plan_id=plan.id,
                    event_type="task_result_discarded",
                    task_id=task.id,
                    task_status=current.status,
                    trace_id=plan.trace_id,
                    execution_id=execution_id,
                    payload={"reason": "stale execution lease"},
                ))
                return
            if result.status == "completed":
                task.status = "completed"
                task.result = result.result
                task.code = result.code
                task.structured_data = result.structured_data
                task.image_base64 = result.image_base64
                task.error = result.error or None
                for artifact_name in task.output_artifacts:
                    value = result.artifact_values.get(artifact_name)
                    if value is None:
                        value = result.code if ("code" in artifact_name or "file_path" in artifact_name) and result.code else result.structured_data or result.result
                    plan.artifacts[artifact_name] = build_artifact(
                        artifact_name,
                        task.id,
                        value,
                        result=result.result,
                        code=result.code,
                        structured_data=result.structured_data,
                    )
                    created_artifact_keys.append(artifact_name)
                event_type = "task_completed"
            else:
                task.result = result.result or None
                task.code = result.code or None
                task.structured_data = result.structured_data or None
                task.image_base64 = result.image_base64 or None
                task.error = result.error or f"executor returned status {result.status}"
                # Failed validation is still a valid scientific outcome. Keep
                # only explicitly returned evidence; never synthesize missing
                # outputs from a failed task's result text.
                for artifact_name in task.output_artifacts:
                    if artifact_name not in result.artifact_values:
                        continue
                    plan.artifacts[artifact_name] = build_artifact(
                        artifact_name,
                        task.id,
                        result.artifact_values[artifact_name],
                        result=result.result,
                        code=result.code,
                        structured_data=result.structured_data,
                    )
                    created_artifact_keys.append(artifact_name)
                event_type = self._schedule_retry_or_fail(task)
        except TimeoutError:
            task.error = f"task timed out after {effective_timeout:g} seconds"
            event_type = self._schedule_retry_or_fail(task)
        except Exception as exc:
            task.error = str(exc)
            event_type = self._schedule_retry_or_fail(task)
        task.finished_at = utc_now() if task.status in TERMINAL_TASK_STATUSES else None
        task.updated_at = utc_now()
        task.lease_owner = None
        task.lease_expires_at = None
        await self.store.save_plan(plan)
        for message in execution_logs:
            await self.events.publish(PlanEvent(
                plan_id=plan.id,
                event_type="task_log",
                task_id=task.id,
                task_status=task.status,
                trace_id=plan.trace_id,
                execution_id=execution_id,
                payload={"message": str(message)[:4000]},
            ))
        if created_artifact_keys:
            await self.events.publish(PlanEvent(
                plan_id=plan.id,
                event_type="artifact_created",
                task_id=task.id,
                task_status=task.status,
                trace_id=plan.trace_id,
                execution_id=execution_id,
                payload={
                    "artifact_keys": created_artifact_keys,
                    "artifacts": {key: plan.artifacts[key] for key in created_artifact_keys},
                },
            ))
        payload = {
            "result": task.result,
            "code": task.code,
            "structured_data": task.structured_data,
            "image_base64": task.image_base64,
        }
        if task.error:
            payload["error"] = task.error
        await self.events.publish(PlanEvent(
            plan_id=plan.id,
            event_type=event_type,
            task_id=task.id,
            task_status=task.status,
            trace_id=plan.trace_id,
            execution_id=execution_id,
            payload=payload,
        ))

    @staticmethod
    def _schedule_retry_or_fail(task: TaskNode) -> str:
        task.execution_id = None
        if task.run_count <= task.retry_limit:
            task.status = "pending"
            return "task_retry_scheduled"
        task.status = "failed"
        return "task_failed"

    def _remaining_duration(self, plan: PlanGraph) -> float:
        if plan.usage.started_at is None:
            return float(plan.budget.max_duration_seconds)
        elapsed = (utc_now() - plan.usage.started_at).total_seconds()
        return max(0.0, plan.budget.max_duration_seconds - elapsed)

    def _duration_budget_exhausted(self, plan: PlanGraph) -> bool:
        return self._remaining_duration(plan) <= 0

    async def _cancel_for_budget(self, plan: PlanGraph, reason: str) -> None:
        for node in plan.nodes:
            if node.status not in TERMINAL_TASK_STATUSES:
                node.status = "canceled"
                node.error = reason
                node.execution_epoch += 1
                node.execution_id = None
                node.lease_owner = None
                node.lease_expires_at = None
                node.finished_at = utc_now()
        plan.status = "canceled"
        plan.usage.finished_at = utc_now()
        await self.store.save_plan(plan)
        await self.events.publish(PlanEvent(
            plan_id=plan.id,
            event_type="plan_budget_exhausted",
            task_status="canceled",
            trace_id=plan.trace_id,
            payload={"reason": reason},
        ))

    async def _cleanup_terminal_runtime(self, plan: PlanGraph) -> None:
        cleanup = getattr(self.executor, "cleanup_plan", None)
        if cleanup is None or "runtime_cleanup_report" in plan.artifacts:
            return
        try:
            report = await cleanup(plan)
        except Exception as exc:
            report = {"status": "failed", "requested": 0, "deleted": [], "failures": [{"error": str(exc)[:1000]}]}
        plan.artifacts["runtime_cleanup_report"] = build_artifact(
            "runtime_cleanup_report",
            "scheduler",
            report,
            result="sandbox runtime cleanup completed",
        )
        await self.store.save_plan(plan)

    @staticmethod
    def _find_task(plan: PlanGraph, task_id: str) -> TaskNode:
        for task in plan.nodes:
            if task.id == task_id:
                return task
        raise KeyError(task_id)

    @staticmethod
    def _block_failed_dependencies(plan: PlanGraph) -> list[tuple[TaskNode, str]]:
        statuses = {node.id: node.status for node in plan.nodes}
        blocked: list[tuple[TaskNode, str]] = []
        for node in plan.nodes:
            upstream = next(
                (dep for dep in node.dependencies if statuses.get(dep) in FAILED_DEPENDENCY_STATUSES),
                None,
            )
            if node.status in {"pending", "ready"} and upstream is not None:
                node.status = "blocked"
                node.error = "upstream dependency failed"
                blocked.append((node, upstream))
        return blocked

    @staticmethod
    def _promote_ready(plan: PlanGraph) -> list[TaskNode]:
        statuses = {node.id: node.status for node in plan.nodes}
        ready: list[TaskNode] = []
        for node in plan.nodes:
            if node.status == "pending" and all(statuses.get(dep) == "completed" for dep in node.dependencies):
                node.status = "ready"
            if node.status == "ready":
                ready.append(node)
        return ready
