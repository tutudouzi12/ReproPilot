from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.trajectory import verify_trajectory  # noqa: E402


def read_json(path: Path, *, required: bool = True) -> dict[str, Any] | None:
    if not path.is_file():
        if required:
            raise ValueError(f"required trajectory artifact is missing: {path.name}")
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"trajectory artifact must contain a JSON object: {path.name}")
    return payload


def verify_artifact_directory(path: Path) -> dict[str, Any]:
    artifact = path.resolve(strict=True)
    if not artifact.is_dir():
        raise ValueError("trajectory artifact path must be a directory")
    spec = read_json(artifact / "frozen-spec.json")
    assert spec is not None
    ledger = read_json(artifact / "trial-ledger.json", required=False)
    validation = read_json(artifact / "validation-report.json", required=False)
    result = read_json(artifact / "result.json", required=False)
    failure = result.get("failure") if result is not None else None
    if failure is not None and not isinstance(failure, dict):
        raise ValueError("result failure binding must be a JSON object")
    verification = verify_trajectory(
        (artifact / "trajectory.jsonl").read_text(encoding="utf-8"),
        (artifact / "trajectory-manifest.json").read_text(encoding="utf-8"),
        spec_sha256=str(spec.get("spec_sha256") or ""),
        ledger=ledger,
        validation=validation,
        failure=failure,
    )
    return verification.model_dump(mode="json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify hash-linked AutoResearch trajectory artifacts.")
    parser.add_argument("artifact_dir", type=Path, help="Directory containing trajectory.jsonl and bound evidence files")
    return parser.parse_args()


def main() -> int:
    try:
        verification = verify_artifact_directory(parse_args().artifact_dir)
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 1
    print(json.dumps(verification, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
