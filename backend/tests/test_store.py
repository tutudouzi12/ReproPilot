from __future__ import annotations

import pytest

from app.models import PlanEvent
from app.planner import Planner
from app.store import FilePlanStore, PlanNotFound


@pytest.mark.asyncio
async def test_store_persists_plans_events_and_returns_deep_copies(tmp_path):
    path = tmp_path / "state" / "plans.json"
    plan = Planner().build_plan(Planner().classify("运行 Python 代码"))
    plan.trace_id = "trace-persisted"
    plan.nodes[0].contract.input_artifacts = ["paper"]

    first = FilePlanStore(path)
    await first.save_plan(plan)
    await first.append_event(
        PlanEvent(plan_id=plan.id, trace_id=plan.trace_id, event_type="plan_created")
    )

    # Mutating either the original or a loaded value must not alter the store.
    plan.nodes[0].name = "mutated original"
    loaded = await first.get_plan(plan.id)
    loaded.nodes[0].name = "mutated loaded copy"
    loaded_event = (await first.list_events(plan.id))[0]
    loaded_event.event_type = "mutated_event"

    again = await first.get_plan(plan.id)
    assert again.nodes[0].name not in {"mutated original", "mutated loaded copy"}
    assert (await first.list_events(plan.id))[0].event_type == "plan_created"

    reopened = FilePlanStore(path)
    await reopened.load()
    persisted = await reopened.get_plan(plan.id)
    assert persisted.trace_id == "trace-persisted"
    assert persisted.nodes[0].contract.input_artifacts == ["paper"]
    assert (await reopened.list_events(plan.id))[0].event_type == "plan_created"


@pytest.mark.asyncio
async def test_store_rejects_events_for_unknown_plan(tmp_path):
    store = FilePlanStore(tmp_path / "plans.json")
    with pytest.raises(PlanNotFound):
        await store.append_event(PlanEvent(plan_id="missing", event_type="plan_started"))

