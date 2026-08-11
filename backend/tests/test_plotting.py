from __future__ import annotations

import base64
import json

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.agents import RoutedAgentExecutor
from app.claim_evidence import ClaimCriterion, ClaimRubric, PaperClaim, build_evidence_graph, normalize_rubric
from app.events import EventBus
from app.models import PlanGraph, TaskNode
from app.plotting import PNG_SIGNATURE, render_metric_plot, validate_plot_base64
from app.scheduler import DAGScheduler
from app.store import FilePlanStore


def plot_node(task_type: str = "render_plot", output: str = "plot_image") -> TaskNode:
    return TaskNode(
        name="Render metrics",
        type=task_type,
        description="render verified metrics",
        assigned_to="data_agent",
        output_artifacts=[output],
        inputs={
            "execution_result": {
                "executed": True,
                "exit_code": 0,
                "stdout": '{"accuracy": 0.91, "loss": 0.18}',
            },
        },
    )


def plot_plan(node: TaskNode) -> PlanGraph:
    return PlanGraph(user_intent="plot verified metrics", intent_type="Code_Execution", nodes=[node], edges=[])


def claim_rubric() -> ClaimRubric:
    return normalize_rubric(ClaimRubric(
        paper_title="Plot evidence",
        claims=[PaperClaim(
            title="Measured result",
            statement="The run produced a measured result.",
            criteria=[ClaimCriterion(description="Inspect direct execution evidence.", required_evidence=["run", "metric"])],
        )],
    ))


def test_plot_renderer_creates_deterministic_validated_png_manifest():
    first = render_metric_plot(plot_node().inputs)
    second = render_metric_plot(plot_node().inputs)
    raw = base64.b64decode(first.image_base64, validate=True)

    assert raw.startswith(PNG_SIGNATURE)
    assert first.image_base64 == second.image_base64
    assert first.manifest.sha256 == second.manifest.sha256
    assert (first.manifest.width, first.manifest.height) == (960, 540)
    assert first.manifest.byte_size == len(raw)
    assert first.manifest.source_artifacts == ["execution_result"]
    assert [item.value for item in first.manifest.metrics] == [0.91, 0.18]
    assert validate_plot_base64(first.image_base64)[2] == first.manifest.sha256
    with pytest.raises(ValueError, match="missing image data"):
        validate_plot_base64(base64.b64encode(raw[:33]).decode("ascii"))


def test_plot_renderer_handles_extreme_but_finite_metric_range():
    plot = render_metric_plot({"run_metrics": {"high": 1e308, "low": -1e308}})
    assert validate_plot_base64(plot.image_base64)[0:2] == (960, 540)


@pytest.mark.parametrize(
    ("inputs", "message"),
    [
        ({"execution_result": {"executed": True, "exit_code": 0, "stdout": "done"}}, "structured numeric output"),
        ({"run_metrics": {"accuracy": float("nan")}}, "non-finite"),
        ({"run_metrics": {"accuracy": float("inf")}}, "non-finite"),
        ({"run_metrics": {"evidence_status": "unverified_demo", "accuracy": 1.0}}, "unverified demo"),
        ({"execution_result": {"executed": False, "exit_code": None, "metrics": {"accuracy": 1.0}}}, "not executed"),
    ],
)
def test_plot_renderer_rejects_untrusted_or_empty_metrics(inputs, message):
    with pytest.raises(ValueError, match=message):
        render_metric_plot(inputs)


@pytest.mark.asyncio
async def test_routed_executor_returns_png_and_manifest_for_both_plot_tasks():
    executor = RoutedAgentExecutor(offline_demo_mode=False)
    for task_type, output in (("render_plot", "plot_image"), ("result_visualization", "result_plot")):
        node = plot_node(task_type, output)
        result = await executor.execute(node, plot_plan(node))
        manifest = json.loads(result.structured_data)

        assert result.status == "completed"
        assert result.image_base64 == result.artifact_values[output]
        assert manifest["version"] == "plot.artifact/v1"
        assert manifest["status"] == "verified"
        assert manifest["sha256"] == validate_plot_base64(result.image_base64)[2]


@pytest.mark.asyncio
async def test_scheduler_persists_plot_image_and_emits_it_in_completion_event(tmp_path):
    store = FilePlanStore(tmp_path / "plans.json")
    events = EventBus(store)
    node = plot_node()
    plan = plot_plan(node)
    await store.save_plan(plan)

    await DAGScheduler(store, events, RoutedAgentExecutor(offline_demo_mode=False), 1).execute_plan(plan.id)

    saved = await store.get_plan(plan.id)
    history = await store.list_events(plan.id)
    completed = next(event for event in history if event.event_type == "task_completed")
    assert saved.status == "completed"
    assert saved.nodes[0].image_base64
    assert saved.artifacts["plot_image"]["value"] == saved.nodes[0].image_base64
    assert completed.payload["image_base64"] == saved.nodes[0].image_base64


@pytest.mark.asyncio
async def test_scheduler_routes_validated_plot_into_claim_evidence(tmp_path):
    store = FilePlanStore(tmp_path / "plans.json")
    events = EventBus(store)
    plot = plot_node("result_visualization", "result_plot")
    evidence = TaskNode(
        name="Build claim evidence",
        type="claim_evidence_build",
        description="adjudicate the frozen rubric",
        assigned_to="data_agent",
        dependencies=[plot.id],
        required_artifacts=["claim_rubric", "result_plot"],
        output_artifacts=["claim_evidence_graph", "claim_verification_report"],
    )
    plan = PlanGraph(user_intent="visualize and verify", intent_type="Paper_Reproduction", nodes=[plot, evidence], edges=[])
    plan.artifacts["claim_rubric"] = {"value": claim_rubric().model_dump_json()}
    await store.save_plan(plan)

    await DAGScheduler(store, events, RoutedAgentExecutor(offline_demo_mode=False), 1).execute_plan(plan.id)

    saved = await store.get_plan(plan.id)
    graph = json.loads(saved.artifacts["claim_evidence_graph"]["value"])
    plot_evidence = next(item for item in graph["evidence"] if item["artifact_key"] == "result_plot")
    assert saved.status == "completed"
    assert plot_evidence["available"] is True
    assert graph["summary"]["partially_reproduced"] == 1


def test_direct_execution_sse_carries_valid_png_without_model_key(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OFFLINE_DEMO_MODE", "false")
    store = FilePlanStore(tmp_path / "plans.json")
    events = EventBus(store)
    executor = RoutedAgentExecutor(offline_demo_mode=False)
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "events", events)
    monkeypatch.setattr(main, "scheduler", DAGScheduler(store, events, executor))
    monkeypatch.setattr(main, "agents", executor)
    monkeypatch.setattr(main, "UPLOAD_ROOT", tmp_path / "uploads")

    with TestClient(main.app) as client:
        response = client.post(
            "/api/execute",
            json={
                "task_id": "plot-direct",
                "task_name": "render plot",
                "task_type": "render_plot",
                "task_description": "render verified metrics",
                "assigned_to": "data_agent",
                "inputs": plot_node().inputs,
            },
        )

    payload_line = next(line for line in response.text.splitlines() if line.startswith("data: {") and "image_base64" in line)
    payload = json.loads(payload_line.removeprefix("data: "))
    assert response.status_code == 200
    assert "event: result" in response.text
    assert validate_plot_base64(payload["image_base64"])[0:2] == (960, 540)


def test_claim_evidence_accepts_valid_png_and_excludes_invalid_image_text():
    rubric = claim_rubric()
    criterion = rubric.claims[0].criteria[0]
    proposal = {"findings": [{
        "claim_id": rubric.claims[0].id,
        "criterion_id": criterion.id,
        "status": "verified",
        "confidence": 0.9,
        "evidence_keys": ["result_plot"],
        "reason": "The deterministic figure visualizes executed metrics.",
    }]}
    valid_plot = render_metric_plot({"run_metrics": {"accuracy": 0.9}}).image_base64

    valid = build_evidence_graph(rubric, proposal, {"result_plot": valid_plot})
    invalid = build_evidence_graph(rubric, proposal, {"result_plot": "not-a-png"})

    valid_node = next(node for node in valid.evidence if node.artifact_key == "result_plot")
    invalid_node = next(node for node in invalid.evidence if node.artifact_key == "result_plot")
    assert valid_node.available is True
    assert "validated PNG 960x540" in valid_node.summary
    assert valid.claims[0].criteria[0].status == "verified"
    assert invalid_node.available is False
    assert "invalid plot artifact excluded" in invalid_node.summary
    assert invalid.claims[0].criteria[0].status == "unverifiable"
