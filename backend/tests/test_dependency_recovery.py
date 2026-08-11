from __future__ import annotations

import json

import pytest

from app.agents import RoutedAgentExecutor
from app.dependency_recovery import repair_dependency_set, suggested_python_image
from app.models import PlanGraph, TaskNode


def test_unpins_only_distribution_named_by_pip_error():
    repaired, reason = repair_dependency_set(
        ["torch==1.3.1", "numpy==1.24.0"],
        "ERROR: Could not find a version that satisfies the requirement torch==1.3.1 (from versions: 2.0.0)",
    )
    assert repaired == ["torch", "numpy==1.24.0"]
    assert "torch" in reason


def test_python_version_error_selects_bounded_runtime_image():
    assert suggested_python_image("package Requires-Python >=3.12") == "python:3.12-slim"
    assert suggested_python_image("requires python 4.0") == ""


@pytest.mark.asyncio
async def test_routed_install_retries_with_repaired_dependency_set():
    class FakeSandbox:
        configured = True

        def __init__(self):
            self.commands = []

        async def command(self, sandbox_id, command):
            self.commands.append(command)
            if len(self.commands) == 1:
                return {"exit_code": 1, "stdout": "", "stderr": "No matching distribution found for torch==1.3.1"}
            return {"exit_code": 0, "stdout": "installed", "stderr": ""}

    sandbox = FakeSandbox()
    executor = RoutedAgentExecutor()
    executor.sandbox = sandbox
    task = TaskNode(
        name="install",
        type="install_dependencies",
        description="install",
        assigned_to="sandbox_agent",
        output_artifacts=["prepared_runtime", "dependency_install_report"],
        inputs={"runtime_session": "sandbox-1", "dependency_spec": json.dumps({"packages": ["torch==1.3.1"]})},
    )
    plan = PlanGraph(user_intent="run", intent_type="paper_reproduction", nodes=[task], edges=[])

    result = await executor.execute(task, plan)

    assert result.status == "completed"
    assert sandbox.commands[0][-1] == "torch==1.3.1"
    assert sandbox.commands[1][-1] == "torch"
    report = json.loads(result.artifact_values["dependency_install_report"])
    assert report["status"] == "installed"
    assert len(report["attempts"]) == 2


@pytest.mark.asyncio
async def test_routed_install_recreates_runtime_for_supported_python_upgrade(tmp_path):
    class FakeSandbox:
        configured = True

        def __init__(self):
            self.runtimes = []
            self.deleted = []

        async def command(self, sandbox_id, command):
            if sandbox_id == "sandbox-old":
                return {"exit_code": 1, "stdout": "", "stderr": "package Requires-Python >=3.12"}
            return {"exit_code": 0, "stdout": "installed", "stderr": ""}

        async def create(self, mount_path, image=""):
            self.runtimes.append((mount_path, image))
            return "sandbox-new"

        async def delete(self, sandbox_id):
            self.deleted.append(sandbox_id)

    sandbox = FakeSandbox()
    executor = RoutedAgentExecutor()
    executor.sandbox = sandbox
    task = TaskNode(
        name="install",
        type="install_dependencies",
        description="install",
        assigned_to="sandbox_agent",
        output_artifacts=["prepared_runtime", "dependency_install_report"],
        inputs={
            "workspace_path": str(tmp_path),
            "runtime_session": "sandbox-old",
            "dependency_spec": json.dumps({"packages": ["modern-package"]}),
        },
    )
    plan = PlanGraph(user_intent="run", intent_type="paper_reproduction", nodes=[task], edges=[])

    result = await executor.execute(task, plan)

    assert result.status == "completed"
    assert result.artifact_values["prepared_runtime"] == "sandbox-new"
    assert sandbox.runtimes == [(str(tmp_path), "python:3.12-slim")]
    assert sandbox.deleted == ["sandbox-old"]


@pytest.mark.asyncio
async def test_routed_install_applies_bounded_llm_react_plan():
    class FakeLLM:
        configured = True

        async def complete(self, system, user):
            assert "Allowed actions" in system
            assert "broken-package" in user
            return json.dumps({
                "action": "replace_package",
                "reason": "distribution was renamed",
                "replace_package": "broken-package",
                "with_package": "working-package",
            })

    class FakeSandbox:
        configured = True

        def __init__(self):
            self.commands = []

        async def command(self, sandbox_id, command):
            self.commands.append(command)
            if "broken-package" in command:
                return {"exit_code": 1, "stdout": "", "stderr": "installation failed"}
            return {"exit_code": 0, "stdout": "installed", "stderr": ""}

    sandbox = FakeSandbox()
    executor = RoutedAgentExecutor(FakeLLM())
    executor.sandbox = sandbox
    task = TaskNode(
        name="install",
        type="install_dependencies",
        description="install",
        assigned_to="sandbox_agent",
        output_artifacts=["prepared_runtime", "dependency_install_report"],
        inputs={"runtime_session": "sandbox-1", "dependency_spec": json.dumps({"packages": ["broken-package"]})},
    )
    plan = PlanGraph(user_intent="run", intent_type="Code_Execution", nodes=[task], edges=[])

    result = await executor.execute(task, plan)

    assert result.status == "completed"
    assert sandbox.commands[1][-1] == "working-package"
    report = json.loads(result.artifact_values["dependency_install_report"])
    assert report["attempts"][0]["recovery"].startswith("ReAct replace_package")
