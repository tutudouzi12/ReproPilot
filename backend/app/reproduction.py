from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field


SMOKE_RUNNER_NAME = "repropilot_smoke.py"
DEPENDENCY_FILES = {
    "requirements.txt",
    "environment.yml",
    "environment.yaml",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "pipfile",
}
SKIPPED_DIRECTORIES = {
    ".git",
    ".github",
    ".repropilot",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
    "docs",
}


class ReproductionResourceProbe(BaseModel):
    cpu_count: int
    memory_gb: float
    disk_free_gb: float
    gpu_count: int
    gpu_names: list[str] = Field(default_factory=list)
    thresholds: dict[str, float | int]


class ReproductionModeDecision(BaseModel):
    requested_mode: str
    effective_mode: str
    full_eligible: bool
    reasons: list[str] = Field(default_factory=list)
    probe: ReproductionResourceProbe


class ReproductionEntry(BaseModel):
    selected_code_file: str = ""
    dependency_files: list[str] = Field(default_factory=list)
    code_file_candidates: list[str] = Field(default_factory=list)
    repro_entry_kind: str = ""
    mode_decision: ReproductionModeDecision


def scan_repository_workspace(workspace: str | Path) -> tuple[list[Path], list[Path]]:
    root = Path(workspace).resolve(strict=True)
    dependencies: list[Path] = []
    candidates: list[Path] = []
    for current, directories, files in os.walk(root):
        directories[:] = sorted(name for name in directories if name.lower() not in SKIPPED_DIRECTORIES)
        directory = Path(current)
        for name in sorted(files):
            path = directory / name
            if path.is_symlink() or not path.is_file():
                continue
            lowered = name.lower()
            if lowered in DEPENDENCY_FILES:
                dependencies.append(path)
            if lowered.endswith(".py"):
                candidates.append(path)
    candidates.sort(key=lambda path: (-code_file_score(path), path.relative_to(root).as_posix()))
    return dependencies, candidates


def code_file_score(path: str | Path) -> int:
    candidate = Path(path)
    base = candidate.name.lower()
    full = candidate.as_posix().lower()
    score = {
        "the_annotated_transformer.py": 100,
        "main.py": 50,
        "train.py": 40,
        "run.py": 30,
    }.get(base, 0)
    if "annotated" in full and "transformer" in full:
        score += 60
    if "attention" in full and "transformer" in full:
        score += 30
    if any(marker in full for marker in ("test", "example", "demo")):
        score -= 20
    if any(marker in full for marker in ("tutorial", "notebook")):
        score -= 10
    return score


def decide_reproduction_mode(
    inputs: dict[str, Any],
    workspace: str | Path,
    *,
    probe: ReproductionResourceProbe | None = None,
) -> ReproductionModeDecision:
    requested = normalize_reproduction_mode(os.getenv("PAPER_REPRO_MODE") or str(inputs.get("requested_reproduction_mode", "auto")))
    full_requested = _as_bool(inputs.get("full_reproduction_requested")) or requested == "full"
    resources = probe or probe_reproduction_resources(workspace)
    reasons = _ineligibility_reasons(resources)
    eligible = not reasons
    effective = "smoke"
    if requested == "smoke":
        reasons.insert(0, "smoke mode explicitly requested")
    elif requested == "full":
        if eligible:
            effective = "full"
            reasons = ["full reproduction enabled: resources satisfy configured thresholds"]
        else:
            reasons.insert(0, "full reproduction requested but resources are insufficient")
    elif full_requested and eligible:
        effective = "full"
        reasons = ["auto mode enabled full reproduction for an explicit full run request"]
    elif not full_requested:
        reasons.insert(0, "auto mode kept smoke reproduction because a full run was not requested")
    return ReproductionModeDecision(
        requested_mode=requested,
        effective_mode=effective,
        full_eligible=eligible,
        reasons=reasons,
        probe=resources,
    )


def probe_reproduction_resources(workspace: str | Path) -> ReproductionResourceProbe:
    thresholds = {
        "min_cpu_count": _env_int("PAPER_REPRO_FULL_MIN_CPU", 16),
        "min_memory_gb": _env_float("PAPER_REPRO_FULL_MIN_MEMORY_GB", 64.0),
        "min_disk_free_gb": _env_float("PAPER_REPRO_FULL_MIN_DISK_GB", 100.0),
        "min_cuda_gpu": _env_int("PAPER_REPRO_FULL_MIN_GPU", 1),
    }
    root = Path(workspace).resolve(strict=True)
    gpu_names = _cuda_gpu_names()
    return ReproductionResourceProbe(
        cpu_count=os.cpu_count() or 1,
        memory_gb=round(_memory_gb(), 1),
        disk_free_gb=round(shutil.disk_usage(root).free / 1024**3, 1),
        gpu_count=len(gpu_names),
        gpu_names=gpu_names,
        thresholds=thresholds,
    )


def prepare_reproduction_entry(
    workspace: str | Path,
    inputs: dict[str, Any],
    *,
    probe: ReproductionResourceProbe | None = None,
) -> ReproductionEntry:
    root = Path(workspace).resolve(strict=True)
    dependency_files, candidates = scan_repository_workspace(root)
    decision = decide_reproduction_mode(inputs, root, probe=probe)
    selected = candidates[0] if candidates else None
    kind = "repository_full_experiment" if decision.effective_mode == "full" else "repository_selected_entry"
    if decision.effective_mode == "smoke" and _is_attention_repository(root, inputs):
        runner = root / SMOKE_RUNNER_NAME
        variants = _selected_ablation_variants(inputs.get("ablation_plan"))
        code = build_attention_ablation_runner(variants) if variants else build_attention_smoke_runner((root / "src" / "architectures" / "machine_translation_transformer.py").is_file())
        runner.write_text(code, encoding="utf-8")
        selected = runner
        candidates = [runner, *[path for path in candidates if path != runner]]
        kind = "attention_structure_ablation" if variants else "bounded_forward_pass"
    return ReproductionEntry(
        selected_code_file=str(selected) if selected else "",
        dependency_files=[path.relative_to(root).as_posix() for path in dependency_files],
        code_file_candidates=[path.relative_to(root).as_posix() for path in candidates],
        repro_entry_kind=kind if selected else "",
        mode_decision=decision,
    )


def normalize_reproduction_mode(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"smoke", "minimal", "mini", "quick", "最小", "快速"}:
        return "smoke"
    if normalized in {"full", "complete", "bleu", "完整", "全量"}:
        return "full"
    return "auto"


def build_attention_smoke_runner(use_repository_transformer: bool) -> str:
    if use_repository_transformer:
        return '''import json
import os
import sys
import time

import torch

sys.path.insert(0, os.path.join(os.getcwd(), "src"))
from architectures.machine_translation_transformer import MachineTranslationTransformer


def main():
    torch.manual_seed(0)
    config = {"d_model": 64, "n_blocks": 2, "n_heads": 4, "d_ff": 128, "dropout_proba": 0.0,
              "src_vocab_size": 96, "trg_vocab_size": 96, "batch_size": 2, "src_seq_len": 8, "trg_seq_len": 9}
    model = MachineTranslationTransformer(
        d_model=config["d_model"], n_blocks=config["n_blocks"], src_vocab_size=config["src_vocab_size"],
        trg_vocab_size=config["trg_vocab_size"], n_heads=config["n_heads"], d_ff=config["d_ff"],
        dropout_proba=config["dropout_proba"])
    model.eval()
    source = torch.randint(1, config["src_vocab_size"], (config["batch_size"], config["src_seq_len"]))
    target = torch.randint(1, config["trg_vocab_size"], (config["batch_size"], config["trg_seq_len"]))
    started = time.perf_counter()
    with torch.no_grad():
        output = model(source, target)
    metrics = {"status": "ok", "reproduction_scope": "bounded_forward_pass",
               "paper": "Attention Is All You Need", "repo_entry": "src/architectures/machine_translation_transformer.py",
               "model_config": config, "output_shape": list(output.shape),
               "parameter_count": sum(parameter.numel() for parameter in model.parameters()),
               "forward_elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
               "output_abs_mean": round(float(output.abs().mean().item()), 6)}
    print(json.dumps(metrics, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
'''
    return '''import json
import time

import torch
import torch.nn as nn


def main():
    torch.manual_seed(0)
    config = {"d_model": 64, "n_blocks": 2, "n_heads": 4, "d_ff": 128, "dropout_proba": 0.0,
              "batch_size": 2, "src_seq_len": 8, "trg_seq_len": 7}
    model = nn.Transformer(d_model=config["d_model"], nhead=config["n_heads"],
                           num_encoder_layers=config["n_blocks"], num_decoder_layers=config["n_blocks"],
                           dim_feedforward=config["d_ff"], dropout=config["dropout_proba"], batch_first=True)
    model.eval()
    source = torch.randn(config["batch_size"], config["src_seq_len"], config["d_model"])
    target = torch.randn(config["batch_size"], config["trg_seq_len"], config["d_model"])
    started = time.perf_counter()
    with torch.no_grad():
        output = model(source, target)
    metrics = {"status": "ok", "reproduction_scope": "bounded_forward_pass",
               "paper": "Attention Is All You Need", "repo_entry": "generic_torch_transformer_smoke",
               "model_config": config, "output_shape": list(output.shape),
               "parameter_count": sum(parameter.numel() for parameter in model.parameters()),
               "forward_elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
               "output_abs_mean": round(float(output.abs().mean().item()), 6)}
    print(json.dumps(metrics, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
'''


def build_attention_ablation_runner(variants: list[dict[str, Any]]) -> str:
    encoded = json.dumps(variants, ensure_ascii=True, separators=(",", ":"))
    return f'''import json
import math
import time

import torch
import torch.nn as nn


DMODEL = 64
VARIANTS = json.loads(r\'''{encoded}\''')


class AblationAttention(nn.Module):
    def __init__(self, heads, use_scaling=True, use_residual=True):
        super().__init__()
        if DMODEL % heads:
            raise ValueError("d_model must be divisible by heads")
        self.heads = heads
        self.head_dim = DMODEL // heads
        self.use_scaling = use_scaling
        self.use_residual = use_residual
        self.qkv = nn.Linear(DMODEL, DMODEL * 3, bias=False)
        self.output = nn.Linear(DMODEL, DMODEL, bias=False)

    def forward(self, values):
        batch, length, _ = values.shape
        qkv = self.qkv(values).reshape(batch, length, 3, self.heads, self.head_dim)
        query, key, value = qkv.unbind(dim=2)
        query, key, value = (item.transpose(1, 2) for item in (query, key, value))
        scores = query @ key.transpose(-2, -1)
        if self.use_scaling:
            scores = scores / math.sqrt(self.head_dim)
        weights = torch.softmax(scores, dim=-1)
        attended = (weights @ value).transpose(1, 2).contiguous().reshape(batch, length, DMODEL)
        output = self.output(attended)
        return (output + values if self.use_residual else output), weights


def run_variant(config, shared_state):
    torch.manual_seed(config["seed"])
    values = torch.randn(config["batch_size"], config["sequence_length"], DMODEL)
    model = AblationAttention(config["heads"], config["use_scaling"], config["use_residual"])
    model.load_state_dict(shared_state)
    model.eval()
    started = time.perf_counter()
    with torch.no_grad():
        output, weights = model(values)
    entropy = -(weights.clamp_min(1e-12) * weights.clamp_min(1e-12).log()).sum(dim=-1).mean()
    return {{**config, "latency_ms": round((time.perf_counter() - started) * 1000, 6),
            "attention_entropy": round(float(entropy.item()), 6),
            "output_l2": round(float(output.norm().item()), 6),
            "parameter_count": sum(parameter.numel() for parameter in model.parameters())}}


def main():
    torch.manual_seed(20260717)
    reference = AblationAttention(4, True, True)
    results = [run_variant(config, reference.state_dict()) for config in VARIANTS]
    baseline = results[0]
    for result in results:
        relative = {{}}
        for metric in ("latency_ms", "attention_entropy", "output_l2", "parameter_count"):
            base = float(baseline[metric])
            relative[metric] = round((float(result[metric]) - base) / abs(base) * 100, 6) if base else None
        result["relative_to_baseline_pct"] = relative
    print(json.dumps({{"status": "ok", "reproduction_scope": "attention_structure_ablation",
                      "paper": "Attention Is All You Need", "results": results}}, sort_keys=True))


if __name__ == "__main__":
    main()
'''


def _selected_ablation_variants(raw: Any) -> list[dict[str, Any]]:
    if not raw:
        return []
    try:
        payload = raw if isinstance(raw, dict) else json.loads(str(raw))
    except json.JSONDecodeError:
        return []
    selected = payload.get("selected", []) if isinstance(payload, dict) else []
    if not isinstance(selected, list) or not selected:
        return []
    variants = [{"name": "baseline", "category": "baseline", "heads": 4, "use_scaling": True, "use_residual": True, "batch_size": 2, "sequence_length": 16, "seed": 20260717}]
    category_variants = {
        "parameter": {"name": "heads_2", "heads": 2},
        "module": {"name": "no_scaling", "use_scaling": False},
        "data_scale": {"name": "sequence_8", "sequence_length": 8},
        "seed_stability": {"name": "seed_17", "seed": 17},
        "runtime_cost": {"name": "batch_1", "batch_size": 1},
    }
    seen = set()
    for item in selected:
        category = str(item.get("category", "")) if isinstance(item, dict) else ""
        if category in seen or category not in category_variants:
            continue
        seen.add(category)
        variant = dict(variants[0])
        variant.update(category_variants[category], category=category)
        variants.append(variant)
    return variants if len(variants) > 1 else []


def _is_attention_repository(root: Path, inputs: dict[str, Any]) -> bool:
    context = " ".join(str(inputs.get(key, "")) for key in ("repo_url", "paper_title", "paper_search_query")).lower()
    if "attention is all you need" in context or "transformer" in context:
        return True
    for name in ("README.md", "readme.md"):
        path = root / name
        if path.is_file() and not path.is_symlink():
            text = path.read_text(encoding="utf-8", errors="replace")[:256_000].lower()
            if "attention is all you need" in text or "transformer" in text:
                return True
    return False


def _ineligibility_reasons(probe: ReproductionResourceProbe) -> list[str]:
    thresholds = probe.thresholds
    checks = (
        (probe.cpu_count, int(thresholds["min_cpu_count"]), "cpu_count"),
        (probe.memory_gb, float(thresholds["min_memory_gb"]), "memory_gb"),
        (probe.disk_free_gb, float(thresholds["min_disk_free_gb"]), "disk_free_gb"),
        (probe.gpu_count, int(thresholds["min_cuda_gpu"]), "cuda_gpu_count"),
    )
    return [f"{name}={actual} < required={required}" for actual, required, name in checks if actual < required]


def _memory_gb() -> float:
    if os.name == "nt":
        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                        ("available", ctypes.c_ulonglong), ("total_page", ctypes.c_ulonglong),
                        ("available_page", ctypes.c_ulonglong), ("total_virtual", ctypes.c_ulonglong),
                        ("available_virtual", ctypes.c_ulonglong), ("available_extended", ctypes.c_ulonglong)]

        status = MemoryStatus()
        status.length = ctypes.sizeof(MemoryStatus)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return status.total / 1024**3
    meminfo = Path("/proc/meminfo")
    if meminfo.is_file():
        for line in meminfo.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("MemTotal:"):
                return float(line.split()[1]) / 1024**2
    return 0.0


def _cuda_gpu_names(run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run) -> list[str]:
    try:
        result = run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _env_int(name: str, fallback: int) -> int:
    try:
        value = int(os.getenv(name, str(fallback)))
        return value if value >= 0 else fallback
    except ValueError:
        return fallback


def _env_float(name: str, fallback: float) -> float:
    try:
        value = float(os.getenv(name, str(fallback)))
        return value if value >= 0 else fallback
    except ValueError:
        return fallback


def _as_bool(value: Any) -> bool:
    return value is True or str(value).strip().lower() in {"true", "1"}
