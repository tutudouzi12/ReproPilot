from __future__ import annotations

import pytest

from app.agents import RoutedAgentExecutor
from app.events import EventBus
from app.models import PlanGraph, TaskExecutionResult, TaskNode
from app.scheduler import DAGScheduler
from app.store import FilePlanStore


@pytest.mark.asyncio
async def test_executor_cleanup_deduplicates_runtime_artifacts():
    class FakeSandbox:
        def __init__(self):
            self.deleted = []

        async def delete(self, runtime):
            self.deleted.append(runtime)

    executor = RoutedAgentExecutor()
    executor.sandbox = FakeSandbox()
    plan = PlanGraph(
        user_intent="run",
        intent_type="Code_Execution",
        nodes=[],
        edges=[],
        artifacts={
            "runtime_session": {"value": "sandbox-1"},
            "prepared_runtime": {"value": "sandbox-1"},
            "branch_runtime_session": {"value": "sandbox-2"},
            "offline_prepared_runtime": {"value": "offline-runtime"},
            "metrics": {"value": "not-a-runtime"},
        },
    )

    report = await executor.cleanup_plan(plan)

    assert executor.sandbox.deleted == ["sandbox-1", "sandbox-2"]
    assert report["status"] == "completed"
    assert report["requested"] == 2


@pytest.mark.asyncio
async def test_scheduler_cleans_runtime_after_successful_plan(tmp_path):
    class CleanupExecutor:
        def __init__(self):
            self.cleanup_calls = 0

        async def execute(self, task, plan):
            return TaskExecutionResult(
                status="completed",
                result="sandbox-1",
                artifact_values={"runtime_session": "sandbox-1", "prepared_runtime": "sandbox-1"},
            )

        async def cleanup_plan(self, plan):
            self.cleanup_calls += 1
            return {"status": "completed", "requested": 1, "deleted": ["sandbox-1"], "failures": []}

    node = TaskNode(
        id="runtime",
        name="runtime",
        type="prepare_runtime",
        description="runtime",
        assigned_to="sandbox_agent",
        output_artifacts=["runtime_session", "prepared_runtime"],
    )
    plan = PlanGraph(user_intent="run", intent_type="Code_Execution", nodes=[node], edges=[])
    store = FilePlanStore(tmp_path / "plans.json")
    await store.load()
    await store.save_plan(plan)
    events = EventBus(store)
    executor = CleanupExecutor()
    scheduler = DAGScheduler(store, events, executor)

    await scheduler.execute_plan(plan.id)

    saved = await store.get_plan(plan.id)
    assert saved.status == "completed"
    assert executor.cleanup_calls == 1
    assert saved.artifacts["runtime_cleanup_report"]["value"]["deleted"] == ["sandbox-1"]


@pytest.mark.asyncio
async def test_scheduler_cleans_runtime_after_downstream_failure(tmp_path):
    class CleanupExecutor:
        def __init__(self):
            self.cleanup_calls = 0

        async def execute(self, task, plan):
            if task.id == "runtime":
                return TaskExecutionResult(
                    status="completed",
                    result="sandbox-failed-plan",
                    artifact_values={"runtime_session": "sandbox-failed-plan"},
                )
            return TaskExecutionResult(status="failed", error="experiment failed")

        async def cleanup_plan(self, plan):
            self.cleanup_calls += 1
            runtime = plan.artifacts["runtime_session"]["value"]
            return {"status": "completed", "requested": 1, "deleted": [runtime], "failures": []}

    runtime = TaskNode(
        id="runtime",
        name="runtime",
        type="prepare_runtime",
        description="runtime",
        assigned_to="sandbox_agent",
        output_artifacts=["runtime_session"],
    )
    failing = TaskNode(
        id="experiment",
        name="experiment",
        type="execute_code",
        description="run",
        assigned_to="sandbox_agent",
        dependencies=[runtime.id],
        retry_limit=0,
    )
    plan = PlanGraph(user_intent="run", intent_type="Code_Execution", nodes=[runtime, failing], edges=[])
    store = FilePlanStore(tmp_path / "plans.json")
    await store.save_plan(plan)
    executor = CleanupExecutor()

    await DAGScheduler(store, EventBus(store), executor, 1).execute_plan(plan.id)

    saved = await store.get_plan(plan.id)
    assert saved.status == "failed"
    assert executor.cleanup_calls == 1
    assert saved.artifacts["runtime_cleanup_report"]["value"]["deleted"] == ["sandbox-failed-plan"]
