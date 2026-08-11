from __future__ import annotations

import json

import pytest

from app.agents import RoutedAgentExecutor
from app.models import PlanGraph, TaskNode


def task(code: str) -> TaskNode:
    return TaskNode(
        name="Execute generated code",
        type="execute_code",
        description="run a bounded calculation",
        assigned_to="sandbox_agent",
        output_artifacts=["metrics"],
        inputs={"generated_code": code, "prepared_runtime": "sandbox-1"},
    )


@pytest.mark.asyncio
async def test_missing_module_is_installed_once_then_code_is_rerun():
    class OfflineLLM:
        configured = False

    class FakeSandbox:
        configured = True

        def __init__(self):
            self.runs = 0
            self.install = []

        async def run_python_in(self, sandbox_id, code):
            self.runs += 1
            if self.runs == 1:
                return {"exit_code": 1, "stdout": "", "stderr": "ModuleNotFoundError: No module named 'yaml'"}
            return {"exit_code": 0, "stdout": "ok", "stderr": ""}

        async def command(self, sandbox_id, command):
            self.install.append(command)
            return {"exit_code": 0, "stdout": "installed", "stderr": ""}

    sandbox = FakeSandbox()
    executor = RoutedAgentExecutor(OfflineLLM())
    executor.sandbox = sandbox
    node = task("import yaml\nprint('ok')\n")
    plan = PlanGraph(user_intent="run", intent_type="Code_Execution", nodes=[node], edges=[])

    result = await executor.execute(node, plan)

    assert result.status == "completed"
    assert sandbox.runs == 2
    assert sandbox.install[0][-1] == "PyYAML"
    assert "runtime dependency recovery" in json.loads(result.result)["recovery_logs"][0]


@pytest.mark.asyncio
async def test_generated_code_gets_one_policy_checked_llm_repair():
    class FakeLLM:
        configured = True

        async def complete(self, system, user):
            assert "Repair one generated Python snippet" in system
            assert "SyntaxError" in user
            return "```python\nprint({'mean': 2})\n```"

    class FakeSandbox:
        configured = True

        def __init__(self):
            self.codes = []

        async def run_python_in(self, sandbox_id, code):
            self.codes.append(code)
            if len(self.codes) == 1:
                return {"exit_code": 1, "stdout": "", "stderr": "SyntaxError: invalid syntax"}
            return {"exit_code": 0, "stdout": '{"mean": 2}', "stderr": ""}

        async def command(self, sandbox_id, command):
            raise AssertionError("no dependency installation expected")

    sandbox = FakeSandbox()
    executor = RoutedAgentExecutor(FakeLLM())
    executor.sandbox = sandbox
    node = task("print({'mean': })\n")
    plan = PlanGraph(user_intent="calculate mean", intent_type="Code_Execution", nodes=[node], edges=[])

    result = await executor.execute(node, plan)

    assert result.status == "completed"
    assert len(sandbox.codes) == 2
    assert result.code == "print({'mean': 2})"
    assert "runtime code repair applied once" in json.loads(result.result)["recovery_logs"]


@pytest.mark.asyncio
async def test_runtime_repair_rejects_new_network_or_fake_metric_behavior():
    class FakeLLM:
        configured = True

        async def complete(self, system, user):
            return "import requests\nrequests.get('https://example.com')\nprint('fake metric')\n"

    class FakeSandbox:
        configured = True

        async def run_python_in(self, sandbox_id, code):
            return {"exit_code": 1, "stdout": "", "stderr": "SyntaxError: invalid syntax"}

        async def command(self, sandbox_id, command):
            raise AssertionError("no dependency installation expected")

    executor = RoutedAgentExecutor(FakeLLM())
    executor.sandbox = FakeSandbox()
    node = task("print({'mean': })\n")
    plan = PlanGraph(user_intent="calculate", intent_type="Code_Execution", nodes=[node], edges=[])

    result = await executor.execute(node, plan)

    assert result.status == "failed"
    assert "repair rejected" in " ".join(json.loads(result.result)["recovery_logs"])
