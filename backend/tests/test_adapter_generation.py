from __future__ import annotations

import json

import pytest

from app.adapter_generation import collect_repository_context, generate_benchmark_adapter
from app.benchmark import DatasetManifest


def safe_adapter(marker="generated"):
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


def manifest():
    return DatasetManifest(
        name="reviews.csv", format="csv", sha256="a" * 64, size=10, row_count=3, columns=[],
        input_column="review", target_column="label", suggested_task="classification",
        mapping_confidence=1, requires_confirmation=False,
    )


@pytest.mark.asyncio
async def test_two_stage_adapter_generation_uses_bounded_context_and_scoped_files(tmp_path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "README.md").write_text("Run python evaluate.py with a local model.", encoding="utf-8")
    (workspace / "evaluate.py").write_text("def predict(text):\n    return text.upper()\n", encoding="utf-8")
    prompts = []
    responses = [
        json.dumps({"status": "ready", "candidates": [{"kind": "native_eval", "entrypoint": "evaluate.py:predict", "confidence": 0.92, "evidence": "README and evaluate.py"}], "selected_index": 0, "reason": "native API documented"}),
        json.dumps({"status": "ready", "strategy": "native_eval", "entrypoint": "evaluate.py:predict", "confidence": 0.9, "metrics": ["accuracy"], "dependencies": [], "reason": "uses repository function", "adapter_code": safe_adapter()}),
    ]

    async def model_call(prompt):
        prompts.append(prompt)
        return responses[len(prompts) - 1]

    artifacts = await generate_benchmark_adapter(workspace, manifest(), model_call)
    assert len(prompts) == 2
    assert all("Dataset manifest" in prompt and "evaluate.py" in prompt for prompt in prompts)
    assert artifacts.spec.status == "generated"
    assert (workspace / ".repropilot" / "benchmark" / "adapter.py").read_text(encoding="utf-8") == safe_adapter()
    assert artifacts.adapter_path.endswith("adapter.py")


def test_repository_context_excludes_unrelated_and_symlink_files(tmp_path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "README.md").write_text("docs", encoding="utf-8")
    (workspace / "predict.py").write_text("def predict(): pass", encoding="utf-8")
    (workspace / "large.bin").write_bytes(b"x" * 100)
    context = collect_repository_context(workspace)
    assert "README.md" in context
    assert "predict.py" in context
    assert "large.bin" not in context

