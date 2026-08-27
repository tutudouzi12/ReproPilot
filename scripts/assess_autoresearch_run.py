from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.run_assessment import RunAssessment, build_assessment, write_assessment_atomic  # noqa: E402


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"assessment source must contain a JSON object: {path.name}")
    return payload


def optional_object(run_dir: Path, name: str) -> dict[str, Any] | None:
    path = run_dir / name
    return read_object(path) if path.is_file() else None


def verify_result_artifact_bindings(run_dir: Path, result: dict[str, Any]) -> None:
    hashes = result.get("artifact_sha256")
    if not isinstance(hashes, dict):
        raise ValueError("result artifact hashes are missing")
    for name in (
        "frozen-spec.json",
        "trial-ledger.json",
        "validation-report.json",
        "trajectory.jsonl",
        "trajectory-manifest.json",
    ):
        path = run_dir / name
        is_bound = name in hashes
        if not path.is_file() and is_bound:
            raise ValueError(f"result binds a missing assessment source: {name}")
        if not path.is_file():
            continue
        expected = str(hashes.get(name, "")).lower()
        if len(expected) != 64 or any(character not in "0123456789abcdef" for character in expected):
            raise ValueError(f"result does not bind assessment source: {name}")
        if sha256_file(path) != expected:
            raise ValueError(f"assessment source SHA-256 mismatch: {name}")


def assess_run_directory(run_dir: Path, *, allow_derived_legacy: bool) -> RunAssessment:
    selected = run_dir.resolve(strict=True)
    spec = read_object(selected / "frozen-spec.json")
    ledger = optional_object(selected, "trial-ledger.json")
    validation = optional_object(selected, "validation-report.json")
    result = optional_object(selected, "result.json")
    if result is not None:
        verify_result_artifact_bindings(selected, result)
    trajectory_path = selected / "trajectory.jsonl"
    manifest_path = selected / "trajectory-manifest.json"
    trajectory_jsonl = trajectory_path.read_text(encoding="utf-8") if trajectory_path.is_file() else None
    trajectory_manifest = read_object(manifest_path) if manifest_path.is_file() else None
    if (trajectory_jsonl is None or trajectory_manifest is None) and not allow_derived_legacy:
        raise ValueError("run lacks native trajectory evidence; pass --allow-derived-legacy for a partial assessment")
    failure = result.get("failure") if isinstance(result, dict) and isinstance(result.get("failure"), dict) else None
    return build_assessment(
        spec=spec,
        ledger=ledger,
        validation=validation,
        trajectory_jsonl=trajectory_jsonl,
        trajectory_manifest=trajectory_manifest,
        failure=failure,
        result=result,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build deterministic Outcome/Compliance/Process facts for a run.")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--allow-derived-legacy",
        action="store_true",
        help="Allow a partial assessment when hash-linked trajectory artifacts predate the run",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        output = args.output.resolve()
        if output.exists():
            raise ValueError(f"refusing to overwrite assessment output: {output}")
        assessment = assess_run_directory(args.run_dir, allow_derived_legacy=args.allow_derived_legacy)
        write_assessment_atomic(output, assessment)
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 1
    print(
        json.dumps(
            {
                "status": "built",
                "trajectory_source": assessment.evidence.trajectory_source,
                "integrity": assessment.evidence.integrity,
                "outcome": assessment.outcome.status,
                "compliance": assessment.compliance.status,
                "process": assessment.process.status,
                "scoring": assessment.scoring.status,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
