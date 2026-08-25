from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


EVENT_VERSION = "autoresearch.trajectory-event/v1"
MANIFEST_VERSION = "autoresearch.trajectory-manifest/v1"
GENESIS_SHA256 = "0" * 64
MAX_EVENT_BYTES = 16_384
MAX_EVENTS = 10_000
MAX_PAYLOAD_DEPTH = 5
MAX_PAYLOAD_ITEMS = 64
MAX_PAYLOAD_STRING = 512
EVENT_TYPES = {
    "baseline",
    "proposal",
    "apply_patch",
    "guard",
    "public_evaluation",
    "decision",
    "rollback",
    "hidden_validation",
    "finish",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def evidence_sha256(value: Any) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return canonical_sha256(value)


def _validate_payload(value: Any, depth: int = 0) -> None:
    if depth > MAX_PAYLOAD_DEPTH:
        raise ValueError("trajectory payload exceeds maximum nesting depth")
    if value is None or isinstance(value, (bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("trajectory payload contains a non-finite number")
        return
    if isinstance(value, str):
        if len(value) > MAX_PAYLOAD_STRING:
            raise ValueError("trajectory payload string exceeds maximum length")
        return
    if isinstance(value, list):
        if len(value) > MAX_PAYLOAD_ITEMS:
            raise ValueError("trajectory payload list exceeds maximum length")
        for item in value:
            _validate_payload(item, depth + 1)
        return
    if isinstance(value, Mapping):
        if len(value) > MAX_PAYLOAD_ITEMS:
            raise ValueError("trajectory payload object exceeds maximum size")
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > 96:
                raise ValueError("trajectory payload contains an invalid key")
            _validate_payload(item, depth + 1)
        return
    raise ValueError(f"trajectory payload contains unsupported type {type(value).__name__}")


class TrajectoryModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TrajectoryEvent(TrajectoryModel):
    version: Literal[EVENT_VERSION] = EVENT_VERSION
    sequence: int = Field(ge=1)
    event_type: str
    occurred_at: datetime
    previous_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload: dict[str, Any]
    event_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, value: str) -> str:
        if value not in EVENT_TYPES:
            raise ValueError(f"unsupported trajectory event type: {value}")
        return value

    @field_validator("occurred_at")
    @classmethod
    def validate_occurred_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("trajectory event time must include a timezone")
        return value

    @field_validator("payload")
    @classmethod
    def validate_payload(cls, value: dict[str, Any]) -> dict[str, Any]:
        _validate_payload(value)
        return value


class TrajectoryManifest(TrajectoryModel):
    version: Literal[MANIFEST_VERSION] = MANIFEST_VERSION
    event_version: Literal[EVENT_VERSION] = EVENT_VERSION
    event_count: int = Field(ge=1)
    first_event_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    last_event_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    trajectory_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    spec_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    ledger_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    validation_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    failure_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    terminal_event: Literal["finish"] = "finish"
    terminal_status: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,95}$")

    @model_validator(mode="after")
    def validate_terminal_bindings(self) -> "TrajectoryManifest":
        if self.ledger_sha256 is None and self.validation_sha256 is None and self.failure_sha256 is None:
            raise ValueError("trajectory manifest requires terminal evidence")
        if self.terminal_status == "passed" and (self.ledger_sha256 is None or self.validation_sha256 is None):
            raise ValueError("passed trajectory manifest requires ledger and validation hashes")
        return self


class TrajectoryVerification(TrajectoryModel):
    status: Literal["verified"] = "verified"
    event_count: int
    trajectory_sha256: str
    last_event_sha256: str
    terminal_status: str


def _event_hash_payload(event: TrajectoryEvent | dict[str, Any]) -> dict[str, Any]:
    if isinstance(event, TrajectoryEvent):
        payload = event.model_dump(mode="json")
    else:
        payload = dict(event)
    payload.pop("event_sha256", None)
    return payload


def _event_sha256(event: TrajectoryEvent | dict[str, Any]) -> str:
    return canonical_sha256(_event_hash_payload(event))


class TrajectoryRecorder:
    def __init__(
        self,
        events: list[TrajectoryEvent] | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.events = list(events or [])
        self.clock = clock or (lambda: datetime.now().astimezone())

    def emit(self, event_type: str, payload: dict[str, Any]) -> TrajectoryEvent:
        if self.events and self.events[-1].event_type == "finish":
            raise ValueError("cannot append to a finalized trajectory")
        if len(self.events) >= MAX_EVENTS:
            raise ValueError("trajectory exceeds maximum event count")
        _validate_payload(payload)
        event_payload = {
            "version": EVENT_VERSION,
            "sequence": len(self.events) + 1,
            "event_type": event_type,
            "occurred_at": self.clock(),
            "previous_sha256": self.events[-1].event_sha256 if self.events else GENESIS_SHA256,
            "payload": payload,
            "event_sha256": GENESIS_SHA256,
        }
        normalized = TrajectoryEvent.model_validate(event_payload).model_dump(mode="json")
        normalized["event_sha256"] = _event_sha256(normalized)
        event = TrajectoryEvent.model_validate(normalized)
        if len(canonical_json(event.model_dump(mode="json")).encode("utf-8")) > MAX_EVENT_BYTES:
            raise ValueError("trajectory event exceeds maximum serialized size")
        self.events.append(event)
        return event

    def jsonl(self) -> str:
        return "".join(f"{canonical_json(event.model_dump(mode='json'))}\n" for event in self.events)

    @classmethod
    def from_jsonl(
        cls,
        value: str,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> "TrajectoryRecorder":
        events = parse_trajectory_jsonl(value, require_terminal=False)
        return cls(events, clock=clock)


TrajectorySink = Callable[[str, dict[str, Any]], object]


def emit_event(event_sink: TrajectorySink | None, event_type: str, payload: dict[str, Any]) -> None:
    if event_sink is not None:
        event_sink(event_type, payload)


def parse_trajectory_jsonl(value: str, *, require_terminal: bool = True) -> list[TrajectoryEvent]:
    if not value or not value.endswith("\n"):
        raise ValueError("trajectory JSONL must be non-empty and newline terminated")
    events: list[TrajectoryEvent] = []
    for line_number, line in enumerate(value.splitlines(), start=1):
        if line_number > MAX_EVENTS:
            raise ValueError("trajectory exceeds maximum event count")
        if not line:
            raise ValueError(f"trajectory contains an empty line at {line_number}")
        if len(line.encode("utf-8")) > MAX_EVENT_BYTES:
            raise ValueError(f"trajectory event {line_number} exceeds maximum serialized size")
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"trajectory line {line_number} is not valid JSON") from exc
        try:
            event = TrajectoryEvent.model_validate(raw)
        except ValidationError as exc:
            raise ValueError(f"trajectory line {line_number} failed schema validation") from exc
        expected_sequence = len(events) + 1
        if event.sequence != expected_sequence:
            raise ValueError(f"trajectory sequence mismatch at event {expected_sequence}")
        expected_previous = events[-1].event_sha256 if events else GENESIS_SHA256
        if event.previous_sha256 != expected_previous:
            raise ValueError(f"trajectory previous hash mismatch at event {expected_sequence}")
        if event.event_sha256 != _event_sha256(event):
            raise ValueError(f"trajectory event hash mismatch at event {expected_sequence}")
        if events and events[-1].event_type == "finish":
            raise ValueError("trajectory contains events after finish")
        events.append(event)
    if events[0].event_type != "baseline":
        raise ValueError("trajectory must begin with baseline")
    if require_terminal and events[-1].event_type != "finish":
        raise ValueError("trajectory does not end with finish")
    return events


def finalize_trajectory(
    recorder: TrajectoryRecorder,
    *,
    spec_sha256: str,
    ledger: BaseModel | dict[str, Any] | None = None,
    validation: BaseModel | dict[str, Any] | None = None,
    failure: BaseModel | dict[str, Any] | None = None,
    terminal_status: str,
) -> TrajectoryManifest:
    if terminal_status == "passed" and (ledger is None or validation is None):
        raise ValueError("passed trajectory requires ledger and validation bindings")
    if ledger is None and validation is None and failure is None:
        raise ValueError("trajectory requires at least one terminal evidence binding")
    ledger_sha256 = evidence_sha256(ledger) if ledger is not None else None
    validation_sha256 = evidence_sha256(validation) if validation is not None else None
    failure_sha256 = evidence_sha256(failure) if failure is not None else None
    finish_payload: dict[str, Any] = {
        "terminal_status": terminal_status,
        "spec_sha256": spec_sha256,
    }
    if ledger_sha256 is not None:
        finish_payload["ledger_sha256"] = ledger_sha256
    if validation_sha256 is not None:
        finish_payload["validation_sha256"] = validation_sha256
    if failure_sha256 is not None:
        finish_payload["failure_sha256"] = failure_sha256
    recorder.emit(
        "finish",
        finish_payload,
    )
    jsonl = recorder.jsonl()
    return TrajectoryManifest(
        event_count=len(recorder.events),
        first_event_sha256=recorder.events[0].event_sha256,
        last_event_sha256=recorder.events[-1].event_sha256,
        trajectory_sha256=hashlib.sha256(jsonl.encode("utf-8")).hexdigest(),
        spec_sha256=spec_sha256,
        ledger_sha256=ledger_sha256,
        validation_sha256=validation_sha256,
        failure_sha256=failure_sha256,
        terminal_status=terminal_status,
    )


def verify_trajectory(
    trajectory_jsonl: str,
    manifest: TrajectoryManifest | dict[str, Any] | str,
    *,
    spec_sha256: str | None = None,
    ledger: BaseModel | dict[str, Any] | None = None,
    validation: BaseModel | dict[str, Any] | None = None,
    failure: BaseModel | dict[str, Any] | None = None,
) -> TrajectoryVerification:
    events = parse_trajectory_jsonl(trajectory_jsonl)
    if isinstance(manifest, str):
        selected_manifest = TrajectoryManifest.model_validate_json(manifest)
    elif isinstance(manifest, TrajectoryManifest):
        selected_manifest = manifest
    else:
        selected_manifest = TrajectoryManifest.model_validate(manifest)
    if selected_manifest.event_count != len(events):
        raise ValueError("trajectory manifest event count mismatch")
    if selected_manifest.first_event_sha256 != events[0].event_sha256:
        raise ValueError("trajectory manifest first event hash mismatch")
    if selected_manifest.last_event_sha256 != events[-1].event_sha256:
        raise ValueError("trajectory manifest last event hash mismatch")
    trajectory_sha256 = hashlib.sha256(trajectory_jsonl.encode("utf-8")).hexdigest()
    if selected_manifest.trajectory_sha256 != trajectory_sha256:
        raise ValueError("trajectory manifest content hash mismatch")
    finish = events[-1].payload
    for field in ("spec_sha256", "ledger_sha256", "validation_sha256", "failure_sha256"):
        if finish.get(field) != getattr(selected_manifest, field):
            raise ValueError(f"trajectory finish {field} mismatch")
    if finish.get("terminal_status") != selected_manifest.terminal_status:
        raise ValueError("trajectory terminal status mismatch")
    if spec_sha256 is not None and selected_manifest.spec_sha256 != spec_sha256:
        raise ValueError("trajectory spec hash mismatch")
    if ledger is not None and selected_manifest.ledger_sha256 != evidence_sha256(ledger):
        raise ValueError("trajectory ledger hash mismatch")
    if validation is not None and selected_manifest.validation_sha256 != evidence_sha256(validation):
        raise ValueError("trajectory validation hash mismatch")
    if failure is not None and selected_manifest.failure_sha256 != evidence_sha256(failure):
        raise ValueError("trajectory failure hash mismatch")
    return TrajectoryVerification(
        event_count=len(events),
        trajectory_sha256=trajectory_sha256,
        last_event_sha256=events[-1].event_sha256,
        terminal_status=selected_manifest.terminal_status,
    )


def write_trajectory_artifacts(
    output: Path,
    recorder: TrajectoryRecorder,
    manifest: TrajectoryManifest,
) -> tuple[Path, Path]:
    verify_trajectory(recorder.jsonl(), manifest)
    output.mkdir(parents=True, exist_ok=True)
    trajectory_path = output / "trajectory.jsonl"
    manifest_path = output / "trajectory-manifest.json"
    temporary_trajectory = output / f".trajectory-{os.getpid()}.tmp"
    temporary_manifest = output / f".trajectory-manifest-{os.getpid()}.tmp"
    try:
        temporary_trajectory.write_text(recorder.jsonl(), encoding="utf-8", newline="\n")
        temporary_manifest.write_text(
            json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(temporary_trajectory, trajectory_path)
        os.replace(temporary_manifest, manifest_path)
    finally:
        for temporary in (temporary_trajectory, temporary_manifest):
            if temporary.exists():
                temporary.unlink()
    return trajectory_path, manifest_path
