from __future__ import annotations

import csv
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


SAMPLE_LIMIT = 1000


class DatasetColumnProfile(BaseModel):
    name: str
    inferred_type: str
    non_null_count: int
    unique_count: int


class DatasetManifest(BaseModel):
    version: str = "benchmark.dataset/v1"
    name: str
    format: str
    sha256: str
    size: int
    row_count: int
    columns: list[DatasetColumnProfile]
    input_column: str = ""
    target_column: str = ""
    suggested_task: str
    mapping_confidence: float
    requires_confirmation: bool
    sample_preview: list[dict[str, str]] = Field(default_factory=list)


class BenchmarkAdapterSpec(BaseModel):
    version: str = "benchmark.adapter/v1"
    status: str
    strategy: str
    entrypoint: str
    confidence: float = 0.0
    dataset_sha256: str
    input_column: str = ""
    target_column: str = ""
    metrics: list[str]
    dependencies: list[str] = Field(default_factory=list)
    adapter_code_sha256: str
    repair_attempts: int = 0
    reason: str = ""


class BenchmarkRunManifest(BaseModel):
    status: str
    dataset_sha256: str
    sample_count: int
    seed: int | None = None
    adapter: str | None = None


class BenchmarkHarnessReport(BaseModel):
    status: str
    mode: str
    sample_count: int
    metrics: dict[str, float]
    predictions_path: str


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def profile_dataset(inputs: dict[str, Any], description: str = "") -> DatasetManifest:
    files = inputs.get("uploaded_files")
    if not isinstance(files, list):
        raise ValueError("uploaded_files input is required")
    primary = next((item for item in files if _supported_regular_upload(item)), None)
    if primary is None:
        raise ValueError("no supported dataset attachment; expected csv, tsv, json, or jsonl")
    path = Path(str(primary["storage_path"]))
    rows, row_count = _read_rows(path, str(primary["name"]))
    if not rows or row_count == 0:
        raise ValueError(f"dataset {primary['name']!r} has no records")
    columns = _profile_columns(rows)
    names = [column.name for column in columns]
    input_hint = str(inputs.get("benchmark_input_column", "")).strip()
    target_hint = str(inputs.get("benchmark_target_column", "")).strip()
    _validate_hint(names, input_hint, "input")
    _validate_hint(names, target_hint, "target")
    input_column, input_explicit = _choose_column(names, input_hint, ["text", "input", "prompt", "question", "sentence", "content", "review", "feature", "features"])
    target_column, target_explicit = _choose_column(names, target_hint, ["label", "target", "class", "y", "answer", "score", "output"])
    if input_column == target_column:
        target_column, target_explicit = "", False
    confidence = 0.4
    if input_column:
        confidence = 0.7
    if input_explicit:
        confidence = 0.9
    if target_column:
        confidence += 0.1
    if target_explicit:
        confidence = 1.0
    checksum = sha256_file(path)
    expected = str(primary.get("sha256", "")).strip()
    if expected and expected.lower() != checksum.lower():
        raise ValueError("uploaded dataset checksum does not match stored metadata")
    allows_input_only = any(word in f"{inputs.get('benchmark_mode', '')} {description}".lower() for word in ("latency", "throughput", "inference", "推理", "延迟", "吞吐"))
    return DatasetManifest(
        name=str(primary["name"]),
        format=Path(str(primary["name"])).suffix.lower().removeprefix("."),
        sha256=checksum,
        size=path.stat().st_size,
        row_count=row_count,
        columns=columns,
        input_column=input_column,
        target_column=target_column,
        suggested_task=_infer_task(rows, input_column, target_column),
        mapping_confidence=min(confidence, 1.0),
        requires_confirmation=not input_column or (not target_column and not allows_input_only),
        sample_preview=[{key: value[:256] + ("..." if len(value) > 256 else "") for key, value in row.items()} for row in rows[:3]],
    )


def validate_adapter_code(code: str) -> None:
    code = code.strip()
    if not code:
        raise ValueError("generated benchmark adapter is empty")
    if len(code.encode("utf-8")) > 200 * 1024:
        raise ValueError("generated benchmark adapter exceeds 200 KiB")
    for token in ("--dataset", "--output-dir", "--limit", "--repo-root", "metrics.json", "predictions.jsonl", "run_manifest.json", "dataset_sha256"):
        if token not in code:
            raise ValueError(f"generated benchmark adapter is missing contract token {token!r}")
    lowered = code.lower()
    for forbidden in (
        "os.remove(", "os.unlink(", ".unlink(", "shutil.rmtree(", "shell=true", "pip install",
        "os.system(", "os.popen(", "subprocess.", "requests.", "httpx.", "aiohttp.", "urllib.request",
        "urllib3.", "socket.socket(", "torch.hub.", "random prediction", "dummy prediction", "fake metric",
    ):
        if forbidden in lowered:
            raise ValueError(f"generated benchmark adapter violates policy: {forbidden}")


def write_adapter_files(workspace: str | Path, code: str, spec: BenchmarkAdapterSpec) -> tuple[Path, Path]:
    validate_adapter_code(code)
    root = Path(workspace).resolve(strict=True)
    repropilot = root / ".repropilot"
    if repropilot.is_symlink():
        raise ValueError(".repropilot must not be a symlink")
    directory = repropilot / "benchmark"
    directory.mkdir(parents=True, exist_ok=True)
    resolved = directory.resolve(strict=True)
    if root != resolved and root not in resolved.parents:
        raise ValueError("benchmark path escaped workspace")
    adapter_path = directory / "adapter.py"
    spec_path = directory / "benchmark.json"
    adapter_path.write_text(code, encoding="utf-8")
    spec_path.write_text(spec.model_dump_json(indent=2), encoding="utf-8")
    return adapter_path, spec_path


def validate_output_directory(
    workspace: str | Path,
    output_relative: str,
    manifest: DatasetManifest,
    limit: int,
    mode: str,
) -> BenchmarkHarnessReport:
    root = Path(workspace).resolve(strict=True)
    output = (root / output_relative).resolve(strict=True)
    if root != output and root not in output.parents:
        raise ValueError("benchmark output escaped workspace")
    metrics = _read_json_object(output / "metrics.json", 1024 * 1024)
    if not metrics or any(not isinstance(value, (int, float)) or not math.isfinite(float(value)) for value in metrics.values()):
        raise ValueError("metrics.json must contain finite numeric metrics")
    run_manifest = BenchmarkRunManifest.model_validate(_read_json_object(output / "run_manifest.json", 1024 * 1024))
    if run_manifest.status != "ok":
        raise ValueError(f"adapter run status is {run_manifest.status!r}")
    if run_manifest.dataset_sha256 != manifest.sha256:
        raise ValueError("adapter dataset hash mismatch")
    if run_manifest.sample_count <= 0 or run_manifest.sample_count > limit or run_manifest.sample_count > manifest.row_count:
        raise ValueError(f"adapter sample count {run_manifest.sample_count} violates limit {limit}")
    predictions_path = output / "predictions.jsonl"
    predictions = _read_predictions(predictions_path, bool(manifest.target_column), run_manifest.sample_count)
    _validate_metrics({key: float(value) for key, value in metrics.items()}, predictions, manifest.suggested_task)
    return BenchmarkHarnessReport(
        status="passed",
        mode=mode,
        sample_count=run_manifest.sample_count,
        metrics={key: float(value) for key, value in metrics.items()},
        predictions_path=predictions_path.relative_to(root).as_posix(),
    )


def _supported_regular_upload(item: Any) -> bool:
    if not isinstance(item, dict) or not str(item.get("name", "")).lower().endswith((".csv", ".tsv", ".json", ".jsonl")):
        return False
    path = Path(str(item.get("storage_path", "")))
    return path.is_file() and not path.is_symlink()


def _read_rows(path: Path, name: str) -> tuple[list[dict[str, str]], int]:
    suffix = Path(name).suffix.lower()
    if suffix in {".csv", ".tsv"}:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="," if suffix == ".csv" else "\t")
            rows = [_stringify(row) for row in reader]
        return rows[:SAMPLE_LIMIT], len(rows)
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            payload = next((payload[key] for key in ("data", "records", "items", "examples") if isinstance(payload.get(key), list)), None)
        if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
            raise ValueError("JSON dataset must be an array of objects or contain data/records/items/examples")
        return [_stringify(item) for item in payload[:SAMPLE_LIMIT]], len(payload)
    rows = []
    count = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            count += 1
            item = json.loads(line)
            if not isinstance(item, dict):
                raise ValueError(f"JSONL record {count} is not an object")
            if len(rows) < SAMPLE_LIMIT:
                rows.append(_stringify(item))
    return rows, count


def _stringify(row: dict[str, Any]) -> dict[str, str]:
    result = {}
    for key, value in row.items():
        if value is None:
            result[str(key)] = ""
        elif isinstance(value, str):
            result[str(key)] = value
        elif isinstance(value, (int, float, bool)):
            result[str(key)] = str(value).lower() if isinstance(value, bool) else str(value)
        else:
            result[str(key)] = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return result


def _profile_columns(rows: list[dict[str, str]]) -> list[DatasetColumnProfile]:
    profiles = []
    for name in sorted({key for row in rows for key in row}):
        values = [row.get(name, "").strip() for row in rows if row.get(name, "").strip()]
        profiles.append(DatasetColumnProfile(name=name, inferred_type=_infer_type(values), non_null_count=len(values), unique_count=len(set(values))))
    return profiles


def _infer_type(values: list[str]) -> str:
    if not values:
        return "unknown"
    try:
        for value in values:
            int(value)
        return "integer"
    except ValueError:
        pass
    try:
        for value in values:
            float(value)
        return "number"
    except ValueError:
        pass
    if all(value.lower() in {"true", "false"} for value in values):
        return "boolean"
    return "string"


def _validate_hint(columns: list[str], hint: str, kind: str) -> None:
    if hint and hint.lower() not in {name.lower() for name in columns}:
        raise ValueError(f"{kind} column {hint!r} does not exist in dataset")


def _choose_column(columns: list[str], explicit: str, candidates: list[str]) -> tuple[str, bool]:
    for name in columns:
        if explicit and name.lower() == explicit.lower():
            return name, True
    for candidate in candidates:
        for name in columns:
            if name.lower() == candidate:
                return name, False
    return (columns[0], False) if columns and not explicit else ("", False)


def _infer_task(rows: list[dict[str, str]], input_column: str, target_column: str) -> str:
    if not input_column:
        return "unknown"
    if not target_column:
        return "inference"
    values = {row.get(target_column, "").strip() for row in rows if row.get(target_column, "").strip()}
    numeric = True
    for value in values:
        try:
            float(value)
        except ValueError:
            numeric = False
    return "regression" if numeric and len(values) > 20 else "classification"


def _read_json_object(path: Path, max_bytes: int) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"adapter did not write a regular {path.name} file")
    if path.stat().st_size > max_bytes:
        raise ValueError(f"{path.name} exceeds {max_bytes} bytes")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must contain an object")
    return payload


def _read_predictions(path: Path, require_target: bool, expected: int) -> list[tuple[Any, Any]]:
    if not path.is_file() or path.is_symlink():
        raise ValueError("adapter did not write a regular predictions.jsonl file")
    records = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        item = json.loads(line)
        if not isinstance(item, dict) or item.get("prediction") is None:
            raise ValueError(f"prediction line {number} is missing prediction")
        if require_target and item.get("target") is None:
            raise ValueError(f"prediction line {number} is missing target")
        records.append((item["prediction"], item.get("target")))
        if len(records) > expected:
            raise ValueError(f"prediction count exceeds declared sample count {expected}")
    if len(records) != expected:
        raise ValueError(f"prediction count {len(records)} does not match sample count {expected}")
    return records


def _validate_metrics(metrics: dict[str, float], predictions: list[tuple[Any, Any]], task_type: str) -> None:
    tolerance = lambda value: max(1e-6, abs(value) * 1e-4)
    if task_type == "classification":
        accuracy, macro_f1 = _classification_metrics(predictions)
        checked = False
        for key, expected in (("accuracy", accuracy), ("macro_f1", macro_f1)):
            reported = next((value for name, value in metrics.items() if name.strip().lower() == key), None)
            if reported is not None:
                checked = True
                if abs(reported - expected) > tolerance(expected):
                    raise ValueError(f"reported {key} {reported:.8f} does not match predictions {expected:.8f}")
        if not checked:
            raise ValueError("classification benchmark must report accuracy or macro_f1")
    elif task_type == "regression":
        values = [(float(prediction), float(target)) for prediction, target in predictions]
        mse = sum((prediction - target) ** 2 for prediction, target in values) / len(values)
        mae = sum(abs(prediction - target) for prediction, target in values) / len(values)
        checked = False
        for key, expected in (("mse", mse), ("mae", mae)):
            reported = next((value for name, value in metrics.items() if name.strip().lower() == key), None)
            if reported is not None:
                checked = True
                if abs(reported - expected) > tolerance(expected):
                    raise ValueError(f"reported {key} {reported:.8f} does not match predictions {expected:.8f}")
        if not checked:
            raise ValueError("regression benchmark must report mse or mae")


def _classification_metrics(predictions: list[tuple[Any, Any]]) -> tuple[float, float]:
    labels = {str(value) for pair in predictions for value in pair}
    correct = sum(str(prediction) == str(target) for prediction, target in predictions)
    f1_sum = 0.0
    for label in labels:
        tp = sum(str(prediction) == label and str(target) == label for prediction, target in predictions)
        fp = sum(str(prediction) == label and str(target) != label for prediction, target in predictions)
        fn = sum(str(prediction) != label and str(target) == label for prediction, target in predictions)
        denominator = 2 * tp + fp + fn
        f1_sum += (2 * tp / denominator) if denominator else 0.0
    return correct / len(predictions), f1_sum / len(labels) if labels else 0.0
