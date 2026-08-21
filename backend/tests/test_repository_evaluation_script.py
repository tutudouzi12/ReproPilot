from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "run_repository_evaluation.py"
SPEC = importlib.util.spec_from_file_location("repository_evaluation_script", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
repository_evaluation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(repository_evaluation)


def test_preserve_python_executable_keeps_virtualenv_symlink(tmp_path: Path) -> None:
    target = tmp_path / "python-target"
    target.write_text("", encoding="utf-8")
    link = tmp_path / "python"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("creating symlinks is not permitted in this environment")

    assert repository_evaluation.preserve_python_executable(link) == link.absolute()


def test_editable_sources_and_patch_support_nested_files(tmp_path: Path) -> None:
    source = tmp_path / "src" / "package" / "module.py"
    source.parent.mkdir(parents=True)
    source.write_text("value = 1\n", encoding="utf-8")

    initial = repository_evaluation.editable_sources(tmp_path, ["src/package/module.py"])
    source.write_text("value = 2\n", encoding="utf-8")
    final = repository_evaluation.editable_sources(tmp_path, ["src/package/module.py"])
    patch = repository_evaluation.candidate_patch(initial, final)

    assert initial == {"src/package/module.py": "value = 1\n"}
    assert "--- a/src/package/module.py" in patch
    assert "+++ b/src/package/module.py" in patch
    assert "-value = 1" in patch
    assert "+value = 2" in patch


def test_write_editable_sources_preserves_repository_paths(tmp_path: Path) -> None:
    output = tmp_path / "evidence"
    output.mkdir()

    repository_evaluation.write_editable_sources(
        output,
        "initial-files",
        {"src/package/module.py": "value = 1\n"},
    )

    retained = output / "initial-files" / "src" / "package" / "module.py"
    assert retained.read_text(encoding="utf-8") == "value = 1\n"


def test_write_editable_sources_rejects_path_escape(tmp_path: Path) -> None:
    output = tmp_path / "evidence"
    output.mkdir()

    with pytest.raises(ValueError, match="escaped output directory"):
        repository_evaluation.write_editable_sources(output, "initial-files", {"../outside.py": ""})


def test_copy_dependency_directory_isolates_installed_packages(tmp_path: Path) -> None:
    source = tmp_path / "checkout" / "node_modules"
    package = source / "sample-package" / "package.json"
    package.parent.mkdir(parents=True)
    package.write_text('{"version":"1.0.0"}\n', encoding="utf-8")
    destination = tmp_path / "workspace" / "node_modules"
    destination.parent.mkdir()

    repository_evaluation.copy_dependency_directory(source, destination)

    assert (destination / "sample-package" / "package.json").read_text(encoding="utf-8") == '{"version":"1.0.0"}\n'
    package.write_text('{"version":"1.0.1"}\n', encoding="utf-8")
    assert (destination / "sample-package" / "package.json").read_text(encoding="utf-8") == '{"version":"1.0.0"}\n'


def test_render_report_separates_attempts_from_usage_reports() -> None:
    result = {
        "recorded_at": "2026-08-21T00:00:00Z",
        "harness": {"revision": "a" * 40},
        "repository": {"revision": "b" * 40, "editable_files": ["source/index.ts"]},
        "outcome": "candidate_stopped",
        "search": {"baseline_score": 0.5, "best_score": 0.5},
        "validation": {
            "baseline_score": 0.4,
            "observed_score": 0.4,
            "acceptance_rule": "minimum_improvement",
            "acceptance_target_score": 1.0,
            "acceptance_delta": 0.6,
        },
        "model": {
            "provider": "provider.example",
            "model": "model-name",
            "attempted_request_count": 3,
            "reported_request_count": 0,
            "total_tokens": 0,
        },
        "cost": {"amount": None, "currency": "CNY"},
    }

    report = repository_evaluation.render_report(result, None, {"title": "sample"})

    assert "Request attempts/usage reports/tokens: `3` / `0` / `0`" in report
