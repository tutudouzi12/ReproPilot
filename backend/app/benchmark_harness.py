from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Awaitable, Callable

from pydantic import BaseModel, Field

from .benchmark import (
    BenchmarkAdapterSpec,
    BenchmarkHarnessReport,
    DatasetManifest,
    sha256_file,
    validate_adapter_code,
    validate_output_directory,
)
from .research_coding import ExecutionResult


class BenchmarkAttempt(BaseModel):
    attempt: int
    exit_code: int
    error: str = ""
    repaired: bool = False


class PreflightResult(BaseModel):
    code: str
    spec: BenchmarkAdapterSpec
    report: BenchmarkHarnessReport
    attempts: list[BenchmarkAttempt]


class BenchmarkHarnessFailure(RuntimeError):
    def __init__(self, message: str, attempts: list[BenchmarkAttempt]) -> None:
        super().__init__(message)
        self.attempts = attempts


Runner = Callable[[str, str, int], Awaitable[ExecutionResult]]
Repairer = Callable[[str, str], Awaitable[str]]


async def preflight_adapter(
    workspace: str | Path,
    dataset_path: str | Path,
    manifest: DatasetManifest,
    spec: BenchmarkAdapterSpec,
    code: str,
    runner: Runner,
    repairer: Repairer,
    max_attempts: int = 3,
) -> PreflightResult:
    root = Path(workspace).resolve(strict=True)
    dataset = Path(dataset_path).resolve(strict=True)
    if root not in dataset.parents:
        raise ValueError("benchmark dataset must be materialized inside workspace")
    _verify_dataset(dataset, manifest)
    validate_adapter_code(code)
    if hashlib.sha256(code.encode()).hexdigest() != spec.adapter_code_sha256:
        raise ValueError("benchmark adapter code hash mismatch")
    attempts: list[BenchmarkAttempt] = []
    current_code = code
    repair_count = 0
    last_error = ""
    for attempt in range(1, max(1, min(3, max_attempts)) + 1):
        result = await runner(current_code, ".repropilot/benchmark/preflight", min(8, manifest.row_count))
        try:
            _verify_dataset(dataset, manifest)
            if result.exit_code != 0:
                raise ValueError(result.stderr or result.stdout or f"exit code {result.exit_code}")
            report = validate_output_directory(root, ".repropilot/benchmark/preflight", manifest, min(8, manifest.row_count), "preflight")
            attempts.append(BenchmarkAttempt(attempt=attempt, exit_code=0, repaired=repair_count > 0))
            validated = spec.model_copy(deep=True)
            validated.status = "preflight_passed"
            validated.repair_attempts = repair_count
            validated.adapter_code_sha256 = hashlib.sha256(current_code.encode()).hexdigest()
            return PreflightResult(code=current_code, spec=validated, report=report, attempts=attempts)
        except ValueError as exc:
            last_error = str(exc)
            attempts.append(BenchmarkAttempt(attempt=attempt, exit_code=result.exit_code, error=last_error, repaired=False))
            if "dataset" in last_error.lower() and "hash" in last_error.lower():
                break
            if attempt >= max_attempts:
                break
            repaired = await repairer(current_code, last_error)
            validate_adapter_code(repaired)
            if repaired.strip() == current_code.strip():
                raise BenchmarkHarnessFailure("benchmark repair produced no effective change", attempts)
            current_code = repaired
            repair_count += 1
            attempts[-1].repaired = True
    raise BenchmarkHarnessFailure(f"benchmark preflight failed: {last_error}", attempts)


async def execute_benchmark(
    workspace: str | Path,
    dataset_path: str | Path,
    manifest: DatasetManifest,
    spec: BenchmarkAdapterSpec,
    code: str,
    runner: Runner,
    limit: int,
) -> BenchmarkHarnessReport:
    root = Path(workspace).resolve(strict=True)
    dataset = Path(dataset_path).resolve(strict=True)
    _verify_dataset(dataset, manifest)
    validate_adapter_code(code)
    if spec.status != "preflight_passed":
        raise ValueError("benchmark adapter must pass preflight before formal execution")
    if hashlib.sha256(code.encode()).hexdigest() != spec.adapter_code_sha256:
        raise ValueError("validated benchmark adapter code hash mismatch")
    bounded_limit = max(1, min(limit, manifest.row_count, 100_000))
    result = await runner(code, ".repropilot/benchmark/run", bounded_limit)
    _verify_dataset(dataset, manifest)
    if result.exit_code != 0:
        raise BenchmarkHarnessFailure(f"benchmark execution failed: {result.stderr or result.stdout}", [BenchmarkAttempt(attempt=1, exit_code=result.exit_code, error=result.stderr or result.stdout)])
    return validate_output_directory(root, ".repropilot/benchmark/run", manifest, bounded_limit, "run")


def _verify_dataset(path: Path, manifest: DatasetManifest) -> None:
    if sha256_file(path) != manifest.sha256:
        raise ValueError("dataset hash mismatch: dataset changed during benchmark execution")

