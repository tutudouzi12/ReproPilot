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
