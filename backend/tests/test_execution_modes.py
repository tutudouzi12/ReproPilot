from __future__ import annotations

import json

import pytest

from app.agent_contracts import build_evidence_report
from app.agents import RoutedAgentExecutor
from app.models import PlanGraph, TaskNode


def plan_for(node: TaskNode) -> PlanGraph:
    return PlanGraph(user_intent="run an experiment", intent_type="Code_Execution", nodes=[node], edges=[])


@pytest.mark.asyncio
async def test_strict_mode_rejects_missing_repository_and_sandbox(monkeypatch):
    monkeypatch.delenv("SANDBOX_URL", raising=False)
    monkeypatch.setenv("REPOSITORY_OPERATIONS_ENABLED", "false")
    executor = RoutedAgentExecutor(offline_demo_mode=False)

    repo = TaskNode(name="prepare", type="repo_prepare", description="prepare", assigned_to="coder_agent")
    runtime = TaskNode(name="runtime", type="prepare_runtime", description="runtime", assigned_to="sandbox_agent")
    execution = TaskNode(
        name="execute",
        type="execute_code",
        description="execute",
        assigned_to="sandbox_agent",
        inputs={"generated_code": "print('ok')", "prepared_runtime": "offline-runtime"},
    )

    assert (await executor.execute(repo, plan_for(repo))).status == "failed"
    assert "REPOSITORY_OPERATIONS_ENABLED=true" in (await executor.execute(repo, plan_for(repo))).error
    assert (await executor.execute(runtime, plan_for(runtime))).status == "failed"
    assert (await executor.execute(execution, plan_for(execution))).status == "failed"


@pytest.mark.asyncio
async def test_offline_demo_never_reports_successful_execution_or_evidence(monkeypatch):
    monkeypatch.delenv("SANDBOX_URL", raising=False)
    executor = RoutedAgentExecutor(offline_demo_mode=True)
    node = TaskNode(
        name="execute",
        type="execute_code",
        description="execute",
        assigned_to="sandbox_agent",
        inputs={"generated_code": "print('ok')", "prepared_runtime": "offline-runtime"},
        output_artifacts=["execution_result"],
    )

    result = await executor.execute(node, plan_for(node))
    payload = json.loads(result.artifact_values["execution_result"])
    report = build_evidence_report("paper_compare", {"run_metrics": result.artifact_values["execution_result"]})

    assert result.status == "completed"
    assert payload["executed"] is False
    assert payload["exit_code"] is None
    assert payload["evidence_status"] == "unverified_demo"
    assert report.metrics == {}
    assert report.evidence_artifacts == []
    assert any("excluded from evidence" in item for item in report.limitations)


@pytest.mark.asyncio
async def test_strict_mode_rejects_model_dependent_placeholder_tasks(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    executor = RoutedAgentExecutor(offline_demo_mode=False)
    framework = TaskNode(
        name="research",
        type="framework_research",
        description="compare frameworks",
        assigned_to="librarian_agent",
    )
    rubric = TaskNode(
        name="rubric",
        type="claim_rubric_extract",
        description="extract claims",
        assigned_to="librarian_agent",
    )

    framework_result = await executor.execute(framework, plan_for(framework))
    rubric_result = await executor.execute(rubric, plan_for(rubric))

    assert framework_result.status == "failed"
    assert "OPENAI_API_KEY" in framework_result.error
    assert rubric_result.status == "failed"
    assert "OPENAI_API_KEY" in rubric_result.error
