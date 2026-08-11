from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.benchmark import BenchmarkAdapterSpec, DatasetManifest, sha256_file
from app.benchmark_harness import BenchmarkHarnessFailure, execute_benchmark, preflight_adapter
from app.agents import RoutedAgentExecutor
from app.models import PlanGraph, TaskNode
from app.research_coding import ExecutionResult


def adapter_code(marker: str) -> str:
    return f'''import argparse
import hashlib
parser = argparse.ArgumentParser()
parser.add_argument("--dataset")
parser.add_argument("--output-dir")
parser.add_argument("--limit", type=int)
parser.add_argument("--repo-root")
dataset_sha256 = hashlib.sha256(open("dataset", "rb").read()).hexdigest()
outputs = ("metrics.json", "predictions.jsonl", "run_manifest.json")
# {marker}
'''


def fixture(tmp_path):
    workspace = tmp_path / "workspace"
    upload_dir = workspace / ".repropilot" / "uploads"
    upload_dir.mkdir(parents=True)
    dataset = upload_dir / "01-reviews.csv"
    dataset.write_text("review,label\none,positive\ntwo,negative\n", encoding="utf-8")
    checksum = sha256_file(dataset)
    manifest = DatasetManifest(
        name="reviews.csv", format="csv", sha256=checksum, size=dataset.stat().st_size, row_count=2,
        columns=[], input_column="review", target_column="label", suggested_task="classification",
        mapping_confidence=1, requires_confirmation=False,
    )
    code = adapter_code("before repair")
    spec = BenchmarkAdapterSpec(
        status="generated", strategy="native_eval", entrypoint="evaluate.py:predict", dataset_sha256=checksum,
        input_column="review", target_column="label", metrics=["accuracy", "macro_f1"],
        adapter_code_sha256=hashlib.sha256(code.encode()).hexdigest(),
    )
    return workspace, dataset, manifest, spec, code


def write_outputs(workspace: Path, relative: str, checksum: str):
    output = workspace / relative
    output.mkdir(parents=True, exist_ok=True)
    (output / "metrics.json").write_text('{"accuracy":0.5,"macro_f1":0.3333333333333333}', encoding="utf-8")
    (output / "run_manifest.json").write_text(json.dumps({"status": "ok", "dataset_sha256": checksum, "sample_count": 2, "seed": 17}), encoding="utf-8")
    (output / "predictions.jsonl").write_text('{"prediction":"positive","target":"positive"}\n{"prediction":"positive","target":"negative"}\n', encoding="utf-8")


@pytest.mark.asyncio
async def test_preflight_repairs_then_formally_executes_and_validates(tmp_path):
    workspace, dataset, manifest, spec, code = fixture(tmp_path)
    calls = 0

    async def runner(current_code, relative, limit):
        nonlocal calls
        calls += 1
        if calls == 1:
            return ExecutionResult(exit_code=1, stderr="ImportError: entrypoint mismatch")
        write_outputs(workspace, relative, manifest.sha256)
        return ExecutionResult(exit_code=0, stdout='{"status":"ok"}')

    async def repairer(current_code, error):
        assert "ImportError" in error
        return adapter_code("after repair")

    preflight = await preflight_adapter(workspace, dataset, manifest, spec, code, runner, repairer, 3)
    assert calls == 2
    assert preflight.spec.status == "preflight_passed"
    assert preflight.spec.repair_attempts == 1
    assert preflight.code == adapter_code("after repair")

    report = await execute_benchmark(workspace, dataset, manifest, preflight.spec, preflight.code, runner, 2)
    assert calls == 3
    assert report.status == "passed"
    assert report.sample_count == 2


@pytest.mark.asyncio
async def test_preflight_rejects_dataset_mutation(tmp_path):
    workspace, dataset, manifest, spec, code = fixture(tmp_path)

    async def runner(current_code, relative, limit):
        dataset.write_text("tampered\n", encoding="utf-8")
        return ExecutionResult(exit_code=0, stdout="ok")

    async def repairer(current_code, error):
        return adapter_code("repair")

    with pytest.raises(BenchmarkHarnessFailure, match="preflight failed"):
        await preflight_adapter(workspace, dataset, manifest, spec, code, runner, repairer, 1)


@pytest.mark.asyncio
async def test_routed_benchmark_runner_rejects_repository_source_mutation(tmp_path):
    workspace, dataset, manifest, spec, code = fixture(tmp_path)
    source = workspace / "model.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")

    class MutatingSandbox:
        configured = True

        async def command(self, sandbox_id, command):
            source.write_text("VALUE = 999\n", encoding="utf-8")
            return {"exit_code": 0, "stdout": "ok", "stderr": ""}

    executor = RoutedAgentExecutor()
    executor.sandbox = MutatingSandbox()
    runner = executor._benchmark_runner(workspace, dataset, "sandbox-1")

    result = await runner(code, ".repropilot/benchmark/preflight", 2)

    assert result.exit_code == 1
    assert "source changed" in result.stderr


@pytest.mark.asyncio
async def test_routed_agent_runs_preflight_formal_benchmark_and_validation(tmp_path):
    workspace, dataset, manifest, spec, code = fixture(tmp_path)

    class FakeSandbox:
        configured = True

        async def command(self, sandbox_id, command):
            assert sandbox_id == "sandbox-1"
            assert command[:3] == ["python", "-I", ".repropilot/benchmark/adapter.py"]
            output_relative = command[command.index("--output-dir") + 1]
            limit = int(command[command.index("--limit") + 1])
            assert 1 <= limit <= manifest.row_count
            write_outputs(workspace, output_relative, manifest.sha256)
            return {"exit_code": 0, "stdout": '{"status":"ok"}', "stderr": ""}

    executor = RoutedAgentExecutor()
    executor.sandbox = FakeSandbox()
    plan = PlanGraph(user_intent="benchmark", intent_type="custom_benchmark", nodes=[], edges=[])
    preflight_task = TaskNode(
        name="preflight",
        type="benchmark_adapter_preflight",
        description="preflight",
        assigned_to="research_coding_agent",
        output_artifacts=["validated_benchmark_adapter_spec", "validated_benchmark_generated_code", "validated_benchmark_code_file_path", "benchmark_preflight_report"],
        inputs={
            "workspace_path": str(workspace),
            "dataset_manifest": manifest.model_dump_json(),
            "benchmark_adapter_spec": spec.model_dump_json(),
            "benchmark_generated_code": code,
            "prepared_runtime": "sandbox-1",
        },
    )
    preflight = await executor.execute(preflight_task, plan)
    assert preflight.status == "completed"

    execute_task = TaskNode(
        name="execute",
        type="benchmark_execute",
        description="formal run",
        assigned_to="research_coding_agent",
        output_artifacts=["benchmark_run_metrics", "benchmark_run_manifest", "benchmark_predictions_path", "benchmark_execution_report"],
        inputs={
            "workspace_path": str(workspace),
            "dataset_manifest": manifest.model_dump_json(),
            "validated_benchmark_adapter_spec": preflight.artifact_values["validated_benchmark_adapter_spec"],
            "validated_benchmark_generated_code": preflight.artifact_values["validated_benchmark_generated_code"],
            "prepared_runtime": "sandbox-1",
            "benchmark_max_samples": 2,
        },
    )
    executed = await executor.execute(execute_task, plan)
    assert executed.status == "completed"

    validate_task = TaskNode(
        name="validate",
        type="benchmark_validate",
        description="validate evidence",
        assigned_to="research_coding_agent",
        output_artifacts=["benchmark_metrics", "benchmark_validation_report"],
        inputs={
            "workspace_path": str(workspace),
            "dataset_manifest": manifest.model_dump_json(),
            "benchmark_run_metrics": executed.artifact_values["benchmark_run_metrics"],
            "benchmark_run_manifest": executed.artifact_values["benchmark_run_manifest"],
            "benchmark_predictions_path": executed.artifact_values["benchmark_predictions_path"],
        },
    )
    validated = await executor.execute(validate_task, plan)
    assert validated.status == "completed"
    assert json.loads(validated.artifact_values["benchmark_metrics"])["accuracy"] == 0.5
    assert json.loads(validated.artifact_values["benchmark_validation_report"])["metrics_recomputed"] is True
