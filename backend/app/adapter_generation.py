from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Awaitable, Callable

from pydantic import BaseModel, Field

from .benchmark import BenchmarkAdapterSpec, DatasetManifest, validate_adapter_code, write_adapter_files


MAX_CONTEXT_FILES = 24
MAX_CONTEXT_BYTES = 96 * 1024
MAX_PER_FILE = 16 * 1024


class AdapterCandidate(BaseModel):
    kind: str
    entrypoint: str
    confidence: float
    evidence: str
    risk: str = ""


class AdapterPlan(BaseModel):
    status: str
    candidates: list[AdapterCandidate]
    selected_index: int
    reason: str


class AdapterGeneration(BaseModel):
    status: str
    strategy: str
    entrypoint: str
    confidence: float
    metrics: list[str]
    dependencies: list[str] = Field(default_factory=list)
    reason: str
    adapter_code: str


class AdapterArtifacts(BaseModel):
    plan: AdapterPlan
    spec: BenchmarkAdapterSpec
    code: str
    adapter_path: str
    spec_path: str


ModelCall = Callable[[str], Awaitable[str]]


async def generate_benchmark_adapter(
    workspace: str | Path,
    manifest: DatasetManifest,
    model_call: ModelCall,
    repo_manifest: str = "",
) -> AdapterArtifacts:
    root = Path(workspace).resolve(strict=True)
    context = collect_repository_context(root, repo_manifest)
    dataset_json = manifest.model_dump_json()
    plan_raw = await model_call(
        "Select a bounded native repository evaluation entrypoint. Return strict JSON with status, candidates, selected_index and reason.\n"
        f"Dataset manifest:\n{dataset_json}\nRepository context:\n{context}"
    )
    plan = AdapterPlan.model_validate(json.loads(clean_json(plan_raw)))
    if plan.status != "ready" or not plan.candidates or not 0 <= plan.selected_index < len(plan.candidates):
        raise ValueError("benchmark adapter plan did not select a valid candidate")
    selected = plan.candidates[plan.selected_index]
    generation_raw = await model_call(
        "Generate a safe benchmark adapter as strict JSON. It must accept --dataset, --output-dir, --limit and --repo-root; write metrics.json, predictions.jsonl and run_manifest.json; compute dataset_sha256; never use network, installs, subprocesses, fake predictions or fake metrics.\n"
        f"Dataset manifest:\n{dataset_json}\nSelected candidate:\n{selected.model_dump_json()}\nRepository context:\n{context}"
    )
    generation = AdapterGeneration.model_validate(json.loads(clean_json(generation_raw)))
    if generation.status != "ready":
        raise ValueError(f"benchmark adapter generation status is {generation.status!r}")
    if generation.entrypoint != selected.entrypoint:
        raise ValueError("generated adapter entrypoint differs from selected bounded plan")
    validate_adapter_code(generation.adapter_code)
    code_hash = hashlib.sha256(generation.adapter_code.encode()).hexdigest()
    spec = BenchmarkAdapterSpec(
        status="generated",
        strategy=generation.strategy,
        entrypoint=generation.entrypoint,
        confidence=max(0.0, min(1.0, generation.confidence)),
        dataset_sha256=manifest.sha256,
        input_column=manifest.input_column,
        target_column=manifest.target_column,
        metrics=generation.metrics,
        dependencies=generation.dependencies,
        adapter_code_sha256=code_hash,
        reason=generation.reason,
    )
    adapter_path, spec_path = write_adapter_files(root, generation.adapter_code, spec)
    return AdapterArtifacts(
        plan=plan,
        spec=spec,
        code=generation.adapter_code,
        adapter_path=str(adapter_path),
        spec_path=str(spec_path),
    )


def collect_repository_context(workspace: str | Path, repo_manifest: str = "") -> str:
    root = Path(workspace).resolve(strict=True)
    candidates = []
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if any(part in {".git", ".repropilot", "node_modules", ".venv", "venv", "__pycache__"} for part in relative.parts):
            continue
        if not path.is_file() or path.is_symlink() or len(relative.parts) > 5:
            continue
        name = path.name.lower()
        suffix = path.suffix.lower()
        if name.startswith("readme"):
            priority = 0
        elif name in {"pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "environment.yml", "environment.yaml"}:
            priority = 1
        elif suffix in {".py", ".yaml", ".yml", ".json", ".toml"} and any(marker in name for marker in ("eval", "test", "infer", "predict", "benchmark", "model", "trainer", "config")):
            priority = 2
        else:
            continue
        candidates.append((priority, relative.as_posix(), path))
    candidates.sort(key=lambda item: (item[0], item[1]))
    parts = []
    used = 0
    if repo_manifest.strip():
        bounded = repo_manifest[:12 * 1024]
        parts.append("Repository manifest:\n" + bounded)
        used += len(bounded.encode())
    for _, relative, path in candidates[:MAX_CONTEXT_FILES]:
        raw = path.read_bytes()[:MAX_PER_FILE]
        remaining = MAX_CONTEXT_BYTES - used
        if remaining <= 0:
            break
        raw = raw[:remaining]
        parts.append(f"--- FILE {relative} ---\n" + raw.decode("utf-8", errors="replace"))
        used += len(raw)
    if not parts:
        raise ValueError("repository contains no readable evaluation or configuration context")
    return "\n\n".join(parts)


def clean_json(raw: str) -> str:
    return raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()

