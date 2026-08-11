from __future__ import annotations

import json

import pytest

from app.agent_contracts import build_evidence_report, offline_paper_parse
from app.agents import RoutedAgentExecutor
from app.models import PlanGraph, TaskNode


def test_offline_paper_parse_does_not_invent_claims_or_metrics():
    report = offline_paper_parse("复现 Attention Is All You Need 的 Transformer")
    assert report.paper_title == "Attention Is All You Need"
    assert report.method_names == ["Transformer"]
    assert report.claims == []
    assert report.reported_metrics == {}
    assert report.status == "partial"


def test_evidence_report_extracts_only_finite_metrics_and_marks_smoke_limit():
    report = build_evidence_report(
        "paper_compare",
        {
            "run_metrics": json.dumps({"accuracy": 0.91, "nested": {"loss": 0.2}}),
            "reproduction_mode_report": json.dumps({"effective_mode": "smoke"}),
            "empty": "",
        },
    )
    assert report.metrics["run_metrics.accuracy"] == 0.91
    assert report.metrics["run_metrics.nested.loss"] == 0.2
    assert set(report.evidence_artifacts) == {"run_metrics", "reproduction_mode_report"}
    assert any("not a verified full reproduction" in item for item in report.limitations)


@pytest.mark.asyncio
async def test_routed_librarian_emits_structured_offline_artifact():
    executor = RoutedAgentExecutor()
    node = TaskNode(
        name="Parse paper",
        type="paper_parse",
        description="parse",
        assigned_to="librarian_agent",
        output_artifacts=["parsed_paper"],
    )
    plan = PlanGraph(user_intent="复现 Attention Is All You Need", intent_type="Paper_Reproduction", nodes=[node], edges=[])

    result = await executor.execute(node, plan)

    payload = json.loads(result.artifact_values["parsed_paper"])
    assert result.status == "completed"
    assert payload["version"] == "agent.paper_parse/v1"
    assert payload["claims"] == []


@pytest.mark.asyncio
async def test_llm_evidence_report_cannot_reference_unknown_artifacts():
    class FakeLLM:
        configured = True

        async def complete(self, system, user):
            return json.dumps({
                "report_type": "paper_compare",
                "status": "analyzed",
                "observations": ["looks good"],
                "metrics": {"accuracy": 1.0},
                "evidence_artifacts": ["invented_metric_file"],
            })

    executor = RoutedAgentExecutor(FakeLLM())
    node = TaskNode(
        name="Compare",
        type="paper_compare",
        description="compare",
        assigned_to="data_agent",
        output_artifacts=["comparison_report"],
        inputs={"run_metrics": '{"accuracy":0.8}'},
    )
    plan = PlanGraph(user_intent="复现论文", intent_type="Paper_Reproduction", nodes=[node], edges=[])

    result = await executor.execute(node, plan)

    assert result.status == "failed"
    assert "unknown evidence artifacts" in result.error
