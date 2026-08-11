from __future__ import annotations

import asyncio

import pytest

from app.research_coding import (
    ExecutionResult,
    PatchProposal,
    RepairProposal,
    debug_paper_code,
    validate_patch_policy,
)
from app.agents import RoutedAgentExecutor
from app.models import PlanGraph, TaskNode


def fixture(tmp_path, source: str):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    entry = workspace / "main.py"
    entry.write_text(source, encoding="utf-8")
    return workspace, entry


async def scripted_runner(entry, always_fail=False):
    raw = entry.read_text(encoding="utf-8")
    if always_fail or "BROKEN" in raw or "still broken" in raw:
        return ExecutionResult(exit_code=1, stderr="RuntimeError: BROKEN")
    return ExecutionResult(exit_code=0, stdout='{"metric":1}')


@pytest.mark.asyncio
async def test_repairs_paper_code_and_records_patch_evidence(tmp_path):
    original = "def evaluate():\n    return 1\n\nraise RuntimeError('BROKEN')\n"
    workspace, entry = fixture(tmp_path, original)

    async def proposer(evidence, files):
        assert "BROKEN" in evidence
        assert "main.py" in files
        return RepairProposal(patches=[PatchProposal(path="main.py", content="def evaluate():\n    return 1\n\nprint(evaluate())", reason="remove unconditional exception")])

    outcome = await debug_paper_code(workspace, entry, scripted_runner, proposer)
    assert outcome.success
    assert len(outcome.report.runs) == 2
    assert len(outcome.report.patches) == 1
    assert outcome.report.patches[0].before_sha256 != outcome.report.patches[0].after_sha256
    assert '"metric":1' in outcome.artifact_values["run_metrics"]


@pytest.mark.asyncio
async def test_gap_debug_patches_before_single_rerun(tmp_path):
    original = "raise RuntimeError('BROKEN')\n"
    workspace, entry = fixture(tmp_path, original)
    calls = 0

    async def runner(path):
        nonlocal calls
        calls += 1
        return await scripted_runner(path)

    async def proposer(evidence, files):
        assert "comparison mismatch" in evidence
        return RepairProposal(patches=[PatchProposal(path="main.py", content="print({'metric': 1})", reason="bounded fix")])

    outcome = await debug_paper_code(workspace, entry, runner, proposer, mode="fix_and_rerun", mismatch_evidence="comparison mismatch")
    assert outcome.success
    assert calls == 1
    assert "rerun_metrics" in outcome.artifact_values
    assert "gap_patch_manifest" in outcome.artifact_values


@pytest.mark.asyncio
async def test_restores_original_when_repair_budget_exhausted(tmp_path):
    original = "raise RuntimeError('BROKEN')\n"
    workspace, entry = fixture(tmp_path, original)
    repair = 0

    async def runner(path):
        return await scripted_runner(path, always_fail=True)

    async def proposer(evidence, files):
        nonlocal repair
        repair += 1
        return RepairProposal(patches=[PatchProposal(path="main.py", content=f"raise RuntimeError('still broken {repair}')", reason="bounded repair")])

    outcome = await debug_paper_code(workspace, entry, runner, proposer, max_repairs=2)
    assert not outcome.success
    assert len(outcome.report.runs) == 3
    assert len(outcome.report.patches) == 2
    assert outcome.report.restored_originals
    assert entry.read_text(encoding="utf-8") == original


@pytest.mark.asyncio
async def test_sandbox_source_mutation_is_detected_and_rolled_back(tmp_path):
    workspace, entry = fixture(tmp_path, "print('ok')\n")
    helper = workspace / "helper.py"
    helper.write_text("VALUE = 1\n", encoding="utf-8")

    async def mutating_runner(path):
        helper.write_text("VALUE = 999\n", encoding="utf-8")
        return ExecutionResult(exit_code=0, stdout="fake success")

    async def unused_proposer(evidence, files):
        raise AssertionError("repair should not run after unauthorized source mutation")

    outcome = await debug_paper_code(workspace, entry, mutating_runner, unused_proposer)

    assert not outcome.success
    assert "source changed during sandbox execution" in outcome.error
    assert helper.read_text(encoding="utf-8") == "VALUE = 1\n"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["no_change", "unsupported"])
async def test_gap_debug_preserves_metrics_when_model_declines_patch(tmp_path, status):
    workspace, entry = fixture(tmp_path, "print({'metric': 1})\n")

    async def runner(path):
        raise AssertionError("no rerun is needed when the model declines a patch")

    async def proposer(evidence, files):
        return RepairProposal(status=status, diagnosis="evidence does not support a code change", patches=[])

    outcome = await debug_paper_code(
        workspace,
        entry,
        runner,
        proposer,
        mode="fix_and_rerun",
        mismatch_evidence="metric gap",
        existing_metrics='{"metric":1}',
    )

    assert outcome.success
    assert outcome.report.status == status
    assert outcome.artifact_values["rerun_metrics"] == '{"metric":1}'
    assert outcome.artifact_values["gap_patch_manifest"] == "[]"


@pytest.mark.asyncio
async def test_research_agent_rejects_task_types_outside_its_contract():
    executor = RoutedAgentExecutor(offline_demo_mode=True)
    task = TaskNode(name="unknown", type="general_response", description="unknown", assigned_to="research_coding_agent")
    plan = PlanGraph(user_intent="unknown", intent_type="General", nodes=[task], edges=[])

    result = await executor.execute(task, plan)

    assert result.status == "failed"
    assert "does not accept task type" in result.error


@pytest.mark.parametrize("patched", [
    "import subprocess\nsubprocess.run(['pip', 'install', 'torch'])\n",
    "import requests\nrequests.get('https://example.com')\n",
    "class FakeModel:\n    pass\n",
    "requests.get(url, verify=False)\n",
])
def test_patch_policy_rejects_side_effects_and_fake_results(patched):
    with pytest.raises(ValueError):
        validate_patch_policy("print(run())\n", patched)
    validate_patch_policy("result = evaluate(model)\n", "result = evaluate(model, batch_size=8)\n")


@pytest.mark.asyncio
async def test_repair_rejects_more_than_three_files(tmp_path):
    workspace, entry = fixture(tmp_path, "raise RuntimeError('BROKEN')\n")
    for index in range(4):
        (workspace / f"helper_{index}.py").write_text(f"VALUE = {index}\n", encoding="utf-8")

    async def proposer(evidence, files):
        return RepairProposal(patches=[
            PatchProposal(path=f"helper_{index}.py", content=f"VALUE = {index + 10}", reason="change")
            for index in range(4)
        ])

    outcome = await debug_paper_code(workspace, entry, scripted_runner, proposer)

    assert not outcome.success
    assert "3-file patch limit" in outcome.error


@pytest.mark.asyncio
async def test_routed_agent_executes_paper_entry_in_persistent_sandbox(tmp_path):
    workspace, entry = fixture(tmp_path, "print({'accuracy': 0.91})\n")

    class FakeSandbox:
        configured = True

        async def command(self, sandbox_id, command):
            assert sandbox_id == "sandbox-1"
            assert command == ["python", "-I", "main.py"]
            return {"exit_code": 0, "stdout": '{"accuracy": 0.91}', "stderr": ""}

    executor = RoutedAgentExecutor()
    executor.sandbox = FakeSandbox()
    task = TaskNode(
        name="paper baseline",
        type="paper_code_execute",
        description="execute repository entry",
        assigned_to="research_coding_agent",
        output_artifacts=["run_metrics", "paper_debug_report", "paper_patch_manifest"],
        inputs={
            "workspace_path": str(workspace),
            "code_file_path": str(entry),
            "prepared_runtime": "sandbox-1",
        },
    )
    plan = PlanGraph(user_intent="reproduce paper", intent_type="paper_reproduction", nodes=[task], edges=[])

    result = await executor.execute(task, plan)

    assert result.status == "completed"
    assert result.artifact_values["run_metrics"] == '{"accuracy": 0.91}'
    assert '"status":"passed"' in result.artifact_values["paper_debug_report"]
    assert result.artifact_values["paper_patch_manifest"] == "[]"
