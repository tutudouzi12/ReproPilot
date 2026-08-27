from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "assess_autoresearch_run.py"
SPEC = importlib.util.spec_from_file_location("assessment_script", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
assessment_script = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(assessment_script)


def test_result_artifact_bindings_reject_mismatch_or_missing_source(tmp_path: Path) -> None:
    spec_path = tmp_path / "frozen-spec.json"
    spec_path.write_text('{}\n', encoding="utf-8")
    result = {"artifact_sha256": {"frozen-spec.json": assessment_script.sha256_file(spec_path)}}

    assessment_script.verify_result_artifact_bindings(tmp_path, result)

    spec_path.write_text('{"changed":true}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="source SHA-256 mismatch: frozen-spec.json"):
        assessment_script.verify_result_artifact_bindings(tmp_path, result)

    spec_path.write_text('{}\n', encoding="utf-8")
    result["artifact_sha256"]["trajectory.jsonl"] = "a" * 64
    with pytest.raises(ValueError, match="binds a missing assessment source: trajectory.jsonl"):
        assessment_script.verify_result_artifact_bindings(tmp_path, result)
