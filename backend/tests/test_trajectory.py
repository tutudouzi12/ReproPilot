from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.trajectory import (
    GENESIS_SHA256,
    TrajectoryRecorder,
    finalize_trajectory,
    verify_trajectory,
    write_trajectory_artifacts,
)


SPEC_SHA256 = "a" * 64
ROOT = Path(__file__).resolve().parents[2]
SCRIPT_SPEC = importlib.util.spec_from_file_location(
    "verify_autoresearch_trajectory_script",
    ROOT / "scripts" / "verify_autoresearch_trajectory.py",
)
assert SCRIPT_SPEC is not None and SCRIPT_SPEC.loader is not None
trajectory_script = importlib.util.module_from_spec(SCRIPT_SPEC)
SCRIPT_SPEC.loader.exec_module(trajectory_script)


def fixed_clock() -> datetime:
    return datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)


def complete_trajectory() -> tuple[TrajectoryRecorder, object, dict, dict]:
    ledger = {"version": "autoresearch.ledger/v1", "spec_sha256": SPEC_SHA256, "best_score": 1.0}
    validation = {"version": "autoresearch.validation/v1", "spec_sha256": SPEC_SHA256, "status": "passed"}
    recorder = TrajectoryRecorder(clock=fixed_clock)
    recorder.emit("baseline", {"score": 0.5, "evidence_sha256": "b" * 64})
    recorder.emit("decision", {"trial": 1, "decision": "keep", "score": 1.0})
    recorder.emit("hidden_validation", {"status": "passed", "evidence_sha256": "c" * 64})
    manifest = finalize_trajectory(
        recorder,
        spec_sha256=SPEC_SHA256,
        ledger=ledger,
        validation=validation,
        terminal_status="passed",
    )
    return recorder, manifest, ledger, validation


def test_hash_linked_trajectory_verifies_against_manifest_ledger_and_validation() -> None:
    recorder, manifest, ledger, validation = complete_trajectory()

    verification = verify_trajectory(
        recorder.jsonl(),
        manifest,
        spec_sha256=SPEC_SHA256,
        ledger=ledger,
        validation=validation,
    )

    assert verification.status == "verified"
    assert verification.event_count == 4
    assert recorder.events[0].previous_sha256 == GENESIS_SHA256
    assert recorder.events[-1].event_type == "finish"
    assert all(
        event.previous_sha256 == recorder.events[index - 1].event_sha256
        for index, event in enumerate(recorder.events[1:], start=1)
    )


@pytest.mark.parametrize("mutation", ["changed", "removed", "duplicated", "reordered", "unknown_field"])
def test_changed_removed_duplicated_or_reordered_events_fail_verification(mutation: str) -> None:
    recorder, manifest, _, _ = complete_trajectory()
    lines = recorder.jsonl().splitlines()
    if mutation == "changed":
        payload = json.loads(lines[1])
        payload["payload"]["score"] = 999
        lines[1] = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    elif mutation == "removed":
        lines.pop(1)
    elif mutation == "duplicated":
        lines.insert(2, lines[1])
    elif mutation == "reordered":
        lines[1], lines[2] = lines[2], lines[1]
    else:
        payload = json.loads(lines[1])
        payload["unhashed_note"] = "must not be ignored"
        lines[1] = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    with pytest.raises(ValueError, match="trajectory"):
        verify_trajectory("\n".join(lines) + "\n", manifest)


def test_manifest_cannot_be_rebound_to_a_different_ledger() -> None:
    recorder, manifest, _, validation = complete_trajectory()

    with pytest.raises(ValueError, match="ledger hash mismatch"):
        verify_trajectory(
            recorder.jsonl(),
            manifest,
            ledger={"version": "autoresearch.ledger/v1", "spec_sha256": SPEC_SHA256, "best_score": 2.0},
            validation=validation,
        )


def test_open_trajectory_can_be_verified_and_continued() -> None:
    recorder = TrajectoryRecorder(clock=fixed_clock)
    recorder.emit("baseline", {"score": 0.5})

    continued = TrajectoryRecorder.from_jsonl(recorder.jsonl(), clock=fixed_clock)
    continued.emit("decision", {"trial": 1, "decision": "reject"})

    assert [event.sequence for event in continued.events] == [1, 2]
    assert continued.events[1].previous_sha256 == continued.events[0].event_sha256


def test_failed_trajectory_binds_failure_evidence_without_claiming_validation() -> None:
    recorder = TrajectoryRecorder(clock=fixed_clock)
    recorder.emit("baseline", {"status": "started", "spec_sha256": SPEC_SHA256})
    recorder.emit("decision", {"trial": 1, "decision": "abort", "status": "integrity_failure"})
    failure = {"error": "RuntimeError: protected evaluator or data changed"}

    manifest = finalize_trajectory(
        recorder,
        spec_sha256=SPEC_SHA256,
        failure=failure,
        terminal_status="integrity_abort",
    )

    verification = verify_trajectory(recorder.jsonl(), manifest, failure=failure)
    assert verification.terminal_status == "integrity_abort"
    assert manifest.ledger_sha256 is None
    assert manifest.validation_sha256 is None
    assert manifest.failure_sha256 is not None


def test_trajectory_rejects_oversized_or_unsupported_payloads() -> None:
    recorder = TrajectoryRecorder(clock=fixed_clock)

    with pytest.raises(ValueError, match="string exceeds"):
        recorder.emit("proposal", {"raw_model_response": "x" * 513})
    with pytest.raises(ValueError, match="unsupported type"):
        recorder.emit("proposal", {"unsafe": object()})
    with pytest.raises(ValueError, match="non-finite"):
        recorder.emit("proposal", {"score": float("nan")})


def test_trajectory_artifacts_are_written_with_canonical_names(tmp_path: Path) -> None:
    recorder, manifest, ledger, validation = complete_trajectory()

    trajectory_path, manifest_path = write_trajectory_artifacts(tmp_path, recorder, manifest)

    assert trajectory_path.name == "trajectory.jsonl"
    assert manifest_path.name == "trajectory-manifest.json"
    verify_trajectory(
        trajectory_path.read_text(encoding="utf-8"),
        manifest_path.read_text(encoding="utf-8"),
        spec_sha256=SPEC_SHA256,
        ledger=ledger,
        validation=validation,
    )
    assert not list(tmp_path.glob(".*.tmp"))


def test_trajectory_verification_script_checks_standard_artifact_directory(tmp_path: Path) -> None:
    recorder, manifest, ledger, validation = complete_trajectory()
    write_trajectory_artifacts(tmp_path, recorder, manifest)
    tmp_path.joinpath("frozen-spec.json").write_text(
        json.dumps({"spec_sha256": SPEC_SHA256}), encoding="utf-8"
    )
    tmp_path.joinpath("trial-ledger.json").write_text(json.dumps(ledger), encoding="utf-8")
    tmp_path.joinpath("validation-report.json").write_text(json.dumps(validation), encoding="utf-8")

    verification = trajectory_script.verify_artifact_directory(tmp_path)

    assert verification["status"] == "verified"
    assert verification["event_count"] == 4
