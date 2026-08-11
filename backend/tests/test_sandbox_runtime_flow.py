from __future__ import annotations

import json

import pytest

from app.agents import RoutedAgentExecutor
from app.events import EventBus
from app.planner import Planner
from app.scheduler import DAGScheduler
from app.store import FilePlanStore


class FakeSandbox:
    configured = True

    def __init__(self):
        self.created = []
        self.commands = []
        self.executions = []

    async def create(self, mount_path):
        self.created.append(mount_path)
        return "dk-fake"

    async def command(self, sandbox_id, command):
        self.commands.append((sandbox_id, command))
        return {"stdout": "installed", "stderr": "", "exit_code": 0}

    async def run_python_in(self, sandbox_id, code):
        self.executions.append((sandbox_id, code))
        return {"stdout": "{'mean_score': 0.8367, 'samples': 3}\n", "stderr": "", "exit_code": 0, "images": []}


@pytest.mark.asyncio
async def test_code_execution_uses_persistent_python_sandbox(tmp_path):
    store = FilePlanStore(tmp_path / "plans.json")
    planner = Planner()
    plan = planner.build_plan(planner.classify("写一个 Python 均值计算代码并运行，然后分析结果"))
    await store.save_plan(plan)
    executor = RoutedAgentExecutor(offline_demo_mode=True)
    fake = FakeSandbox()
    executor.sandbox = fake

    await DAGScheduler(store, EventBus(store), executor, 1).execute_plan(plan.id)

    saved = await store.get_plan(plan.id)
    assert saved.status == "completed", [(node.type, node.status, node.error) for node in saved.nodes]
    assert fake.created == [""]
    assert len(fake.executions) == 1
    assert fake.executions[0][0] == "dk-fake"
    execution = json.loads(saved.artifacts["execution_result"]["value"])
    assert execution["exit_code"] == 0
    assert "mean_score" in execution["stdout"]
