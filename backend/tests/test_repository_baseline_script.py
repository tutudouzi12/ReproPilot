from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "run_repository_baseline.py"
SPEC = importlib.util.spec_from_file_location("repository_baseline_script", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
repository_baseline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(repository_baseline)


def test_sanitize_command_result_replaces_local_paths(tmp_path: Path) -> None:
    checkout = tmp_path / "target-checkout"
    python = tmp_path / "venv" / "Scripts" / "python.exe"
    task_dir = tmp_path / "harness" / "task"
    result = {
        "stdout": f"source={checkout / 'package' / 'module.py'}",
        "stderr": f"python={python.as_posix()}",
        "error": f"evaluator={task_dir / 'evaluator.py'}",
    }

    repository_baseline.sanitize_command_result(
        result,
        [
            (checkout, "{target_checkout}"),
            (python, "{python}"),
            (task_dir, "{task_dir}"),
        ],
    )

    assert "{target_checkout}" in result["stdout"]
    assert "{python}" in result["stderr"]
    assert "{task_dir}" in result["error"]
    for path in (checkout, python, task_dir):
        assert str(path) not in str(result)
        assert path.as_posix() not in str(result)
