from __future__ import annotations

import json
from pathlib import Path

from app.reproduction import (
    ReproductionResourceProbe,
    code_file_score,
    decide_reproduction_mode,
    prepare_reproduction_entry,
    scan_repository_workspace,
)


def probe(*, eligible: bool) -> ReproductionResourceProbe:
    thresholds = {"min_cpu_count": 16, "min_memory_gb": 64.0, "min_disk_free_gb": 100.0, "min_cuda_gpu": 1}
    return ReproductionResourceProbe(
        cpu_count=32 if eligible else 4,
        memory_gb=128 if eligible else 16,
        disk_free_gb=500 if eligible else 20,
        gpu_count=2 if eligible else 0,
        gpu_names=["GPU 0", "GPU 1"] if eligible else [],
        thresholds=thresholds,
    )


def test_repository_scan_scores_real_entrypoints_and_dependency_files(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / "src").mkdir(parents=True)
    (workspace / "tests").mkdir()
    (workspace / "requirements.txt").write_text("torch\n", encoding="utf-8")
    (workspace / "src" / "train.py").write_text("print('train')\n", encoding="utf-8")
    (workspace / "tests" / "test_model.py").write_text("pass\n", encoding="utf-8")
    (workspace / "main.py").write_text("print('main')\n", encoding="utf-8")

    dependencies, candidates = scan_repository_workspace(workspace)

    assert [path.name for path in dependencies] == ["requirements.txt"]
    assert candidates[0].name == "main.py"
    assert code_file_score(workspace / "main.py") > code_file_score(workspace / "tests" / "test_model.py")


def test_full_mode_requires_explicit_request_and_sufficient_resources(tmp_path):
    tmp_path.joinpath("main.py").write_text("print('ok')\n", encoding="utf-8")
    automatic = decide_reproduction_mode({"requested_reproduction_mode": "auto"}, tmp_path, probe=probe(eligible=True))
    assert automatic.effective_mode == "smoke"

    full = decide_reproduction_mode(
        {"requested_reproduction_mode": "auto", "full_reproduction_requested": True},
        tmp_path,
        probe=probe(eligible=True),
    )
    assert full.effective_mode == "full"

    downgraded = decide_reproduction_mode(
        {"requested_reproduction_mode": "full", "full_reproduction_requested": True},
        tmp_path,
        probe=probe(eligible=False),
    )
    assert downgraded.effective_mode == "smoke"
    assert "insufficient" in " ".join(downgraded.reasons)


def test_attention_smoke_mode_creates_bounded_runnable_entry(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "README.md").write_text("# Attention Is All You Need Transformer implementation\n", encoding="utf-8")
    (workspace / "train.py").write_text("raise RuntimeError('full training')\n", encoding="utf-8")

    entry = prepare_reproduction_entry(
        workspace,
        {"requested_reproduction_mode": "smoke"},
        probe=probe(eligible=False),
    )

    selected = Path(entry.selected_code_file)
    assert selected.name == "repropilot_smoke.py"
    assert entry.repro_entry_kind == "bounded_forward_pass"
    assert entry.code_file_candidates[0] == "repropilot_smoke.py"
    code = selected.read_text(encoding="utf-8")
    assert "nn.Transformer" in code
    assert "full training" not in code


def test_full_mode_preserves_repository_entry_instead_of_smoke_runner(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "README.md").write_text("Transformer implementation\n", encoding="utf-8")
    (workspace / "main.py").write_text("print('full')\n", encoding="utf-8")

    entry = prepare_reproduction_entry(
        workspace,
        {"requested_reproduction_mode": "full", "full_reproduction_requested": True},
        probe=probe(eligible=True),
    )

    assert Path(entry.selected_code_file).name == "main.py"
    assert entry.repro_entry_kind == "repository_full_experiment"
    assert not (workspace / "repropilot_smoke.py").exists()
    assert json.loads(entry.mode_decision.model_dump_json())["effective_mode"] == "full"


def test_attention_ablation_runner_uses_selected_tree_categories(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "README.md").write_text("Attention Is All You Need Transformer\n", encoding="utf-8")
    ablation_plan = json.dumps({
        "selected": [
            {"id": "module", "category": "module"},
            {"id": "seed", "category": "seed_stability"},
        ]
    })

    entry = prepare_reproduction_entry(
        workspace,
        {"requested_reproduction_mode": "smoke", "ablation_plan": ablation_plan},
        probe=probe(eligible=False),
    )

    code = Path(entry.selected_code_file).read_text(encoding="utf-8")
    assert entry.repro_entry_kind == "attention_structure_ablation"
    assert '"category":"module"' in code
    assert '"category":"seed_stability"' in code
    assert "no_scaling" in code
    assert "seed_17" in code
    assert '"attention_entropy"' in code
    assert '"relative_to_baseline_pct"' in code
