from __future__ import annotations

import hashlib
import json
import os

import pytest

from app.benchmark import (
    BenchmarkAdapterSpec,
    DatasetManifest,
    profile_dataset,
    sha256_file,
    validate_adapter_code,
    validate_output_directory,
    write_adapter_files,
)


def adapter_code(marker: str = "safe") -> str:
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


def test_profile_csv_infers_contract_and_checksum(tmp_path):
    path = tmp_path / "reviews.csv"
    path.write_text("review,label\ngreat paper,positive\nmissing details,negative\nclear result,positive\n", encoding="utf-8")
    checksum = sha256_file(path)
    manifest = profile_dataset({"uploaded_files": [{"name": path.name, "storage_path": str(path), "sha256": checksum}]})
    assert manifest.row_count == 3
    assert manifest.input_column == "review"
    assert manifest.target_column == "label"
    assert manifest.suggested_task == "classification"
    assert not manifest.requires_confirmation
    assert manifest.sha256 == checksum
    assert len(manifest.sample_preview) == 3


def test_profile_jsonl_supports_explicit_columns(tmp_path):
    path = tmp_path / "records.jsonl"
    path.write_text('{"features":[1,2],"score":0.4}\n{"features":[3,4],"score":0.8}\n', encoding="utf-8")
    manifest = profile_dataset({
        "benchmark_input_column": "features",
        "benchmark_target_column": "score",
        "uploaded_files": [{"name": path.name, "storage_path": str(path)}],
    })
    assert manifest.format == "jsonl"
    assert manifest.row_count == 2
    assert manifest.mapping_confidence == 1


def test_profile_rejects_bad_column_and_checksum(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text("text,label\na,yes\n", encoding="utf-8")
    with pytest.raises(ValueError, match="input column"):
        profile_dataset({"benchmark_input_column": "missing", "uploaded_files": [{"name": path.name, "storage_path": str(path)}]})
    with pytest.raises(ValueError, match="checksum"):
        profile_dataset({"uploaded_files": [{"name": path.name, "storage_path": str(path), "sha256": "deadbeef"}]})


@pytest.mark.parametrize("unsafe", [
    "\nimport requests\nrequests.get('https://example.com')",
    "\nimport subprocess\nsubprocess.run(['python', 'eval.py'])",
    "\n# pip install torch",
])
def test_adapter_policy_rejects_network_and_install_commands(unsafe):
    with pytest.raises(ValueError, match="violates policy"):
        validate_adapter_code(adapter_code() + unsafe)


def test_adapter_write_rejects_workspace_symlink(tmp_path):
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    try:
        os.symlink(outside, workspace / ".repropilot", target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are unavailable on this Windows configuration")
    spec = BenchmarkAdapterSpec(
        status="generated",
        strategy="native_eval",
        entrypoint="evaluate.py:predict",
        dataset_sha256="a" * 64,
        metrics=["accuracy"],
        adapter_code_sha256=hashlib.sha256(adapter_code().encode()).hexdigest(),
    )
    with pytest.raises(ValueError, match="symlink"):
        write_adapter_files(workspace, adapter_code(), spec)
    assert not (outside / "benchmark" / "adapter.py").exists()


def benchmark_output(tmp_path, reported_accuracy: float):
    workspace = tmp_path / "workspace"
    output = workspace / ".repropilot" / "benchmark" / "run"
    output.mkdir(parents=True)
    dataset_sha = "b" * 64
    (output / "metrics.json").write_text(json.dumps({"accuracy": reported_accuracy, "macro_f1": 1 / 3}), encoding="utf-8")
    (output / "run_manifest.json").write_text(json.dumps({"status": "ok", "dataset_sha256": dataset_sha, "sample_count": 2}), encoding="utf-8")
    (output / "predictions.jsonl").write_text('{"prediction":"positive","target":"positive"}\n{"prediction":"positive","target":"negative"}\n', encoding="utf-8")
    manifest = DatasetManifest(
        name="reviews.csv", format="csv", sha256=dataset_sha, size=1, row_count=2, columns=[],
        input_column="review", target_column="label", suggested_task="classification",
        mapping_confidence=1, requires_confirmation=False,
    )
    return workspace, manifest


def test_output_validation_recomputes_metrics(tmp_path):
    workspace, manifest = benchmark_output(tmp_path, 0.5)
    report = validate_output_directory(workspace, ".repropilot/benchmark/run", manifest, 2, "run")
    assert report.status == "passed"
    assert report.sample_count == 2


def test_output_validation_rejects_metric_prediction_mismatch(tmp_path):
    workspace, manifest = benchmark_output(tmp_path, 1.0)
    with pytest.raises(ValueError, match="does not match predictions"):
        validate_output_directory(workspace, ".repropilot/benchmark/run", manifest, 2, "run")
