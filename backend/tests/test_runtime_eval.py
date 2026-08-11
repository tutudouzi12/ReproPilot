from __future__ import annotations

import json
from pathlib import Path

from app.planner import Planner


def test_runtime_planning_eval_dataset():
    dataset = Path(__file__).parents[1] / "evals" / "runtime_eval_dataset.json"
    cases = json.loads(dataset.read_text(encoding="utf-8"))
    planner = Planner()
    assert len(cases) >= 4

    for case in cases:
        context = planner.classify(case["intent"])
        assert context.intent_type == case["expected_intent_type"], case["name"]
        plan = planner.build_plan(context)
        assert len(plan.nodes) >= case["min_nodes"], case["name"]
        assert plan.trace_id
        assert plan.budget.max_task_attempts > 0
        assert plan.budget.max_duration_seconds > 0
        task_types = {node.type for node in plan.nodes}
        for required in case["required_task_types"]:
            assert required in task_types, f"{case['name']}: missing {required}"
        for node in plan.nodes:
            assert node.contract.version == "1.0"
            assert node.contract.allowed_tools
