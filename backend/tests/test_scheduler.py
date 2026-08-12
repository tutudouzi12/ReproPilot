from __future__ import annotations

import asyncio

import pytest

from app.events import EventBus
from app.agents import RoutedAgentExecutor
from app.models import TaskExecutionResult
from app.planner import Planner
from app.scheduler import DAGScheduler, infer_artifact_type
from app.store import FilePlanStore


class FailingExecutor:
    async def execute(self, task, plan):
        if not task.dependencies:
            raise RuntimeError("simulated agent failure")
        return TaskExecutionResult(result="ok")


def test_task_inputs_merge_explicit_values_and_required_artifacts():
    planner = Planner()
    plan = planner.build_plan(planner.classify("运行 Python 代码"))
    task = plan.nodes[0]
    task.inputs = {"paper_title": "Attention Is All You Need"}
    task.required_artifacts = ["parsed_paper"]
    plan.artifacts["parsed_paper"] = {"value": "verified paper payload"}

    inputs = RoutedAgentExecutor._effective_inputs(task, plan)
    assert inputs["paper_title"] == "Attention Is All You Need"
    assert inputs["parsed_paper"] == "verified paper payload"


def test_claim_artifacts_keep_json_contract_type():
    assert infer_artifact_type("claim_rubric") == "json"
    assert infer_artifact_type("claim_evidence_graph") == "json"
    assert infer_artifact_type("claim_verification_report") == "report"


@pytest.mark.asyncio
async def test_failed_dependency_is_blocked(tmp_path):
    store = FilePlanStore(tmp_path / "plans.json")
    await store.load()
    planner = Planner()
    plan = planner.build_plan(planner.classify("研究一个 Python Agent"))
    plan.nodes[0].retry_limit = 0
    await store.save_plan(plan)

    scheduler = DAGScheduler(store, EventBus(store), FailingExecutor())
    await scheduler.execute_plan(plan.id)

    saved = await store.get_plan(plan.id)
    assert saved.status == "failed"
    assert saved.nodes[0].status == "failed"
    assert saved.nodes[1].status == "blocked"
    assert saved.nodes[2].status == "blocked"


@pytest.mark.asyncio
async def test_interrupted_tasks_are_recovered(tmp_path):
    path = tmp_path / "plans.json"
    store = FilePlanStore(path)
    planner = Planner()
    plan = planner.build_plan(planner.classify("研究恢复机制"))
    plan.status = "in_progress"
    plan.nodes[0].status = "in_progress"
    plan.nodes[0].execution_id = "old-run"
    await store.save_plan(plan)

    recovered = FilePlanStore(path)
    await recovered.load()
    saved = await recovered.get_plan(plan.id)
    assert saved.status == "pending"
    assert saved.nodes[0].status == "pending"
    assert saved.nodes[0].execution_id is None
    assert saved.nodes[0].error == "recovered after backend restart"


class RetryExecutor:
    def __init__(self):
        self.attempts = 0

    async def execute(self, task, plan):
        self.attempts += 1
        if self.attempts == 1:
            return TaskExecutionResult(status="failed", error="transient")
        return TaskExecutionResult(status="completed", result="recovered")


@pytest.mark.asyncio
async def test_failed_result_retries_within_limit(tmp_path):
    store = FilePlanStore(tmp_path / "plans.json")
    planner = Planner()
    plan = planner.build_plan(planner.classify("重试测试"))
    plan.nodes = [plan.nodes[0]]
    plan.edges = []
    plan.nodes[0].retry_limit = 1
    await store.save_plan(plan)
    executor = RetryExecutor()

    await DAGScheduler(store, EventBus(store), executor, 1).execute_plan(plan.id)

    saved = await store.get_plan(plan.id)
    assert saved.status == "completed"
    assert saved.nodes[0].run_count == 2
    assert saved.nodes[0].result == "recovered"


@pytest.mark.asyncio
async def test_failed_result_preserves_validation_payload(tmp_path):
    class FailedValidationExecutor:
        async def execute(self, task, plan):
            return TaskExecutionResult(
                status="failed",
                result="validation payload",
                structured_data='{"status":"failed"}',
                error="holdout failed",
            )

    store = FilePlanStore(tmp_path / "plans.json")
    planner = Planner()
    plan = planner.build_plan(planner.classify("验证失败结果持久化"))
    plan.nodes = [plan.nodes[0]]
    plan.edges = []
    plan.nodes[0].retry_limit = 0
    await store.save_plan(plan)

    await DAGScheduler(
        store,
        EventBus(store),
        FailedValidationExecutor(),
        1,
    ).execute_plan(plan.id)

    saved = await store.get_plan(plan.id)
    assert saved.status == "failed"
    assert saved.nodes[0].status == "failed"
    assert saved.nodes[0].result == "validation payload"
    assert saved.nodes[0].structured_data == '{"status":"failed"}'
    assert saved.nodes[0].error == "holdout failed"


class SlowExecutor:
    async def execute(self, task, plan):
        await asyncio.sleep(10)
        return TaskExecutionResult(result="too late")


@pytest.mark.asyncio
async def test_task_timeout_is_enforced(tmp_path):
    store = FilePlanStore(tmp_path / "plans.json")
    planner = Planner()
    plan = planner.build_plan(planner.classify("超时测试"))
    plan.nodes = [plan.nodes[0]]
    plan.edges = []
    plan.nodes[0].retry_limit = 0
    plan.nodes[0].timeout_seconds = 1
    await store.save_plan(plan)

    await DAGScheduler(store, EventBus(store), SlowExecutor(), 1).execute_plan(plan.id)

    saved = await store.get_plan(plan.id)
    assert saved.status == "failed"
    assert "timed out" in (saved.nodes[0].error or "")


@pytest.mark.asyncio
async def test_attempt_budget_cancels_remaining_work(tmp_path):
    store = FilePlanStore(tmp_path / "plans.json")
    planner = Planner()
    plan = planner.build_plan(planner.classify("预算测试"))
    plan.budget.max_task_attempts = 1
    await store.save_plan(plan)

    class SuccessExecutor:
        async def execute(self, task, current_plan):
            return TaskExecutionResult(result="ok")

    await DAGScheduler(store, EventBus(store), SuccessExecutor(), 1).execute_plan(plan.id)

    saved = await store.get_plan(plan.id)
    assert saved.status == "canceled"
    assert saved.usage.task_attempts == 1
    assert saved.nodes[0].status == "completed"
    assert saved.nodes[1].status == "canceled"


@pytest.mark.asyncio
async def test_terminal_plan_cannot_be_canceled(tmp_path):
    store = FilePlanStore(tmp_path / "plans.json")
    planner = Planner()
    plan = planner.build_plan(planner.classify("终态测试"))
    plan.status = "completed"
    for node in plan.nodes:
        node.status = "completed"
    await store.save_plan(plan)

    from app.scheduler import SchedulerConflict

    with pytest.raises(SchedulerConflict):
        await DAGScheduler(store, EventBus(store), SlowExecutor(), 1).cancel(plan.id)


@pytest.mark.asyncio
async def test_retry_resets_all_blocked_descendants(tmp_path):
    store = FilePlanStore(tmp_path / "plans.json")
    planner = Planner()
    plan = planner.build_plan(planner.classify("研究一个 Python Agent"))
    plan.status = "failed"
    plan.nodes[0].status = "failed"
    for node in plan.nodes[1:]:
        node.status = "blocked"
        node.error = "upstream dependency failed"
    await store.save_plan(plan)

    scheduler = DAGScheduler(store, EventBus(store), SlowExecutor(), 1)
    await scheduler.retry_task(plan.id, plan.nodes[0].id)

    saved = await store.get_plan(plan.id)
    assert saved.status == "pending"
    assert all(node.status == "pending" for node in saved.nodes)
    assert all(node.error is None for node in saved.nodes)


class HandoffExecutor:
    def __init__(self):
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def execute(self, task, plan):
        if task.assigned_to == "coder_agent":
            self.started.set()
            await self.release.wait()
        return TaskExecutionResult(result=f"completed by {task.assigned_to}")


@pytest.mark.asyncio
async def test_reassignment_discards_stale_result(tmp_path):
    store = FilePlanStore(tmp_path / "plans.json")
    event_bus = EventBus(store)
    planner = Planner()
    plan = planner.build_plan(planner.classify("任务转交测试"))
    plan.nodes = [plan.nodes[1]]
    plan.nodes[0].dependencies = []
    plan.nodes[0].assigned_to = "coder_agent"
    plan.edges = []
    await store.save_plan(plan)
    executor = HandoffExecutor()
    scheduler = DAGScheduler(store, event_bus, executor, 1)

    running = asyncio.create_task(scheduler.execute_plan(plan.id))
    await asyncio.wait_for(executor.started.wait(), timeout=2)
    await scheduler.reassign_task(plan.id, plan.nodes[0].id, "sandbox_agent")
    executor.release.set()
    await asyncio.wait_for(running, timeout=2)

    saved = await store.get_plan(plan.id)
    assert saved.status == "completed"
    assert saved.nodes[0].assigned_to == "sandbox_agent"
    assert saved.nodes[0].result == "completed by sandbox_agent"
    history = await store.list_events(plan.id)
    assert any(event.event_type == "task_result_discarded" for event in history)


@pytest.mark.asyncio
async def test_canceled_plan_cannot_be_resurrected_by_late_result(tmp_path):
    class CancellationResistantExecutor:
        def __init__(self):
            self.started = asyncio.Event()

        async def execute(self, task, plan):
            self.started.set()
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                return TaskExecutionResult(status="completed", result="late result")
            return TaskExecutionResult(status="completed", result="unexpected")

    store = FilePlanStore(tmp_path / "plans.json")
    node = Planner().build_plan(Planner().classify("运行 Python 代码")).nodes[0]
    node.dependencies = []
    node.retry_limit = 0
    plan = Planner().build_plan(Planner().classify("运行 Python 代码"))
    plan.nodes = [node]
    plan.edges = []
    await store.save_plan(plan)
    executor = CancellationResistantExecutor()
    scheduler = DAGScheduler(store, EventBus(store), executor, 1)

    scheduler.start(plan.id)
    running = scheduler._runs[plan.id]
    await asyncio.wait_for(executor.started.wait(), timeout=2)
    await scheduler.cancel(plan.id)
    with pytest.raises(asyncio.CancelledError):
        await running

    saved = await store.get_plan(plan.id)
    assert saved.status == "canceled"
    assert saved.nodes[0].status == "canceled"
    assert saved.nodes[0].result is None
