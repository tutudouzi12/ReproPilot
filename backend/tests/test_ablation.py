from __future__ import annotations

import json

import pytest

from app.ablation import (
    AblationBudget,
    AblationCandidate,
    default_candidates,
    design_from_model_outputs,
    ensure_category_coverage,
    parse_candidates,
    select_candidates,
)
from app.agents import RoutedAgentExecutor
from app.models import PlanGraph, TaskNode


def test_two_stage_outputs_are_scored_under_budget():
    candidates = '''{"candidates":[
      {"id":"module","category":"module","title":"Remove module","estimated_minutes":8,"estimated_gpu_minutes":4},
      {"id":"runtime","category":"runtime_cost","title":"Measure cost","estimated_minutes":5,"estimated_gpu_minutes":2}
    ]}'''
    evaluations = '''{"evaluations":[
      {"id":"module","information_gain":0.95,"relevance":0.9,"reproducibility":0.8,"risk":0.1,"reason":"Direct test"},
      {"id":"runtime","information_gain":0.5,"relevance":0.6,"reproducibility":0.95,"risk":0.05,"reason":"Cost baseline"}
    ]}'''
    plan = design_from_model_outputs(candidates, evaluations, {
        "ablation_max_experiments": 1,
        "ablation_max_gpu_minutes": 10,
        "ablation_max_wall_minutes": 20,
    })
    assert len(plan.selected) == 1
    assert plan.selected[0].id == "module"


def test_selection_respects_budget_and_category_diversity():
    budget = AblationBudget(max_experiments=2, max_gpu_minutes=0, max_wall_minutes=30)
    plan = select_candidates(default_candidates(), {}, budget)
    assert plan.strategy == "bounded_tree_of_thoughts"
    assert len(plan.selected) == 2
    assert sum(item.estimated_minutes for item in plan.selected) <= 30
    assert len({item.category for item in plan.selected}) == 2


def test_parser_rejects_unknown_categories_and_normalizes_ids():
    raw = '''{"candidates":[
      {"id":"seed test","category":"random_seed","title":"Seed stability","estimated_minutes":12},
      {"id":"unsafe","category":"rewrite_everything","title":"Unbounded rewrite","estimated_minutes":999}
    ]}'''
    candidates = parse_candidates(raw)
    assert len(candidates) == 1
    assert candidates[0].id == "seed_test"
    assert candidates[0].category == "seed_stability"


def test_category_coverage_fills_missing_dimensions():
    generated = [
        AblationCandidate(id="module_a", category="module", title="A"),
        AblationCandidate(id="module_b", category="module", title="B"),
    ]
    merged = ensure_category_coverage(generated)
    assert {item.category for item in merged} >= {"parameter", "module", "data_scale", "seed_stability", "runtime_cost"}
    assert len(merged) <= 8


@pytest.mark.asyncio
async def test_routed_ablation_agent_uses_two_model_stages_before_deterministic_selection():
    class FakeLLM:
        configured = True

        def __init__(self):
            self.calls = []

        async def complete(self, system, user):
            self.calls.append((system, user))
            if len(self.calls) == 1:
                return '{"candidates":[{"id":"module","category":"module","title":"Remove attention scaling","estimated_minutes":8,"estimated_gpu_minutes":2}]}'
            return '{"evaluations":[{"id":"module","information_gain":0.99,"relevance":0.98,"reproducibility":0.9,"risk":0.1,"reason":"direct claim test"}]}'

    llm = FakeLLM()
    executor = RoutedAgentExecutor(llm)
    node = TaskNode(
        name="ablation",
        type="ablation_design",
        description="design",
        assigned_to="data_agent",
        inputs={"ablation_max_experiments": 1, "ablation_max_gpu_minutes": 10, "ablation_max_wall_minutes": 20},
        output_artifacts=["ablation_plan", "selected_ablation_configs", "ablation_selection_report"],
    )
    plan = PlanGraph(user_intent="test an attention ablation", intent_type="Paper_Reproduction", nodes=[node], edges=[])

    result = await executor.execute(node, plan)
    payload = json.loads(result.artifact_values["ablation_plan"])

    assert result.status == "completed"
    assert len(llm.calls) == 2
    assert payload["selected"][0]["id"] == "module"
    assert any("two-stage model" in item for item in result.logs)
