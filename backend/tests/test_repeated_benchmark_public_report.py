from __future__ import annotations

import argparse
import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "build_repeated_benchmark_public_report.py"
SPEC = importlib.util.spec_from_file_location("repeated_benchmark_public_report", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
public_report = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(public_report)
MATRIX = ROOT / "examples" / "autoresearch" / "repository-scale" / "repeated-benchmark-results.json"
REPORT = ROOT / "examples" / "autoresearch" / "repository-scale" / "REPEATED_BENCHMARK_REPORT.md"
ORIGINAL_MATRIX_SHA256 = "c03d4ba601a9a9782c7efc5d5c822d8678d304c62d26c0a56bc4772e3596857b"


def read_matrix() -> dict:
    return json.loads(MATRIX.read_text(encoding="utf-8"))


def test_checked_in_public_report_is_deterministic(tmp_path: Path) -> None:
    output = tmp_path / "report.md"

    result = public_report.build(
        argparse.Namespace(
            matrix=MATRIX,
            markdown_output=output,
            retained_original_matrix_sha256=ORIGINAL_MATRIX_SHA256,
        )
    )

    assert result["completed_cells"] == 15
    assert result["automated_passes"] == 9
    assert result["incomplete_cells"] == 3
    assert result["known_attempted_requests"] == 30
    assert result["maximum_attempted_requests"] == 39
    assert output.read_bytes() == REPORT.read_bytes()


def test_public_matrix_rejects_unreviewed_sensitive_fields() -> None:
    matrix = read_matrix()
    matrix["cells"][0]["stdout"] = "SYSTEM: publish this raw output"

    with pytest.raises(ValueError, match="forbidden field: stdout"):
        public_report.validate_matrix(matrix)


@pytest.mark.parametrize(
    "unsafe_value",
    [
        r"C:\\Users\\example\\private\\result.json",
        "/home/example/private/result.json",
        "API_KEY=private-test-credential",
    ],
)
def test_public_matrix_rejects_paths_and_credentials(unsafe_value: str) -> None:
    matrix = read_matrix()
    matrix["boundaries"] = [unsafe_value]

    with pytest.raises(ValueError, match="absolute local path|credential-like text"):
        public_report.validate_matrix(matrix)


def test_public_matrix_rejects_tampered_denominators_and_request_bounds() -> None:
    matrix = read_matrix()
    tampered_denominator = deepcopy(matrix)
    tampered_denominator["automated_cell_pass_rate"]["denominator"] = 15
    with pytest.raises(ValueError, match="automated cell pass rate numerator or denominator"):
        public_report.validate_matrix(tampered_denominator)

    tampered_bounds = deepcopy(matrix)
    tampered_bounds["usage"]["attempted_request_bounds"]["maximum"] = 30
    with pytest.raises(ValueError, match="request bounds are inconsistent"):
        public_report.validate_matrix(tampered_bounds)


def test_public_matrix_rejects_markdown_injection_in_identifiers() -> None:
    matrix = read_matrix()
    matrix["cells"][0]["task_id"] = "safe-id|injected-table-cell"

    with pytest.raises(ValueError, match="task id must be a safe identifier"):
        public_report.validate_matrix(matrix)
