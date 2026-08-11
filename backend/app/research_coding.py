from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field


class ExecutionResult(BaseModel):
    exit_code: int
    stdout: str = ""
    stderr: str = ""


class PatchProposal(BaseModel):
    path: str
    content: str
    reason: str


class RepairProposal(BaseModel):
    status: str = "patched"
    diagnosis: str = ""
    patches: list[PatchProposal]


class AppliedPatch(BaseModel):
    repair: int
    path: str
    reason: str
    before_sha256: str
    after_sha256: str


class DebugRun(BaseModel):
    attempt: int
    exit_code: int
    stdout: str = ""
    stderr: str = ""


class DebugReport(BaseModel):
    status: str
    summary: str = ""
    runs: list[DebugRun] = Field(default_factory=list)
    patches: list[AppliedPatch] = Field(default_factory=list)
    restored_originals: bool = False
    final_source_fingerprint: str = ""


class DebugOutcome(BaseModel):
    success: bool
    metrics: str = ""
    code: str = ""
    report: DebugReport
    artifact_values: dict[str, str]
    error: str = ""


Runner = Callable[[Path], Awaitable[ExecutionResult]]
Proposer = Callable[[str, dict[str, str]], Awaitable[RepairProposal]]


async def debug_paper_code(
    workspace: str | Path,
    entry_path: str | Path,
    runner: Runner,
    proposer: Proposer,
    *,
    mode: str = "paper_code_execute",
    mismatch_evidence: str = "",
    existing_metrics: str = "",
    max_repairs: int = 2,
) -> DebugOutcome:
    root = Path(workspace).resolve(strict=True)
    entry = _existing_python_path(root, entry_path)
    allowed = _bounded_python_context(root, entry)
    backups: dict[str, tuple[bytes, int]] = {}
    report = DebugReport(status="running")
    failure_evidence = mismatch_evidence
    should_run_first = mode != "fix_and_rerun"

    async def checked_run() -> ExecutionResult:
        snapshot = _source_snapshot(root)
        before = source_fingerprint(root)
        result = await runner(entry)
        if source_fingerprint(root) != before:
            _restore_source_snapshot(root, snapshot)
            raise RuntimeError("repository source changed during sandbox execution")
        return result

    try:
        if should_run_first:
            first = await checked_run()
            report.runs.append(_run_record(1, first))
            if first.exit_code == 0:
                return _complete(root, entry, report, first.stdout, mode)
            failure_evidence = first.stderr or first.stdout

        for repair_number in range(1, max_repairs + 1):
            proposal = await proposer(failure_evidence, dict(allowed))
            if proposal.status in {"no_change", "unsupported"}:
                if mode != "fix_and_rerun":
                    raise RuntimeError(f"paper code repair stopped with status {proposal.status}: {proposal.diagnosis}")
                return _complete_without_change(root, entry, report, existing_metrics, proposal.status, proposal.diagnosis)
            if proposal.status != "patched":
                raise ValueError(f"unknown paper repair status {proposal.status!r}")
            applied = apply_patches(root, proposal.patches, allowed, backups, repair_number)
            report.patches.extend(applied)
            allowed = _bounded_python_context(root, entry)
            result = await checked_run()
            report.runs.append(_run_record(len(report.runs) + 1, result))
            if result.exit_code == 0:
                return _complete(root, entry, report, result.stdout, mode)
            failure_evidence = result.stderr or result.stdout
        raise RuntimeError(f"paper code repair budget exhausted after {max_repairs} repair attempts: {failure_evidence[:500]}")
    except Exception as exc:
        if backups:
            restore_backups(root, backups)
            report.restored_originals = True
        report.status = "failed"
        report.summary = str(exc)
        report.final_source_fingerprint = source_fingerprint(root)
        payload = report.model_dump_json()
        return DebugOutcome(success=False, report=report, artifact_values={}, error=str(exc), code=entry.read_text(encoding="utf-8"), metrics=payload)


def validate_patch_policy(original: str, patched: str) -> None:
    original_lower = original.lower()
    patched_lower = patched.lower()
    forbidden = (
        "pip install", "fake metric", "dummy metric", "mock metric", "fabricated metric", "hardcoded metric",
        "random prediction", "dummy prediction", "hardcoded prediction", "mockllm", "fakeembedding", "fakemodel",
        "os.system(", "os.popen(", "shell=true", "shell = true", "requests.", "httpx.", "aiohttp.",
        "urllib.request", "urllib3.", "socket.socket(", "torch.hub.", "ssl._create_unverified_context",
        "verify=false", "verify = false",
    )
    for marker in forbidden:
        if marker in patched_lower and marker not in original_lower:
            raise ValueError(f"introduced forbidden construct {marker!r}")
    if "subprocess." in patched_lower and "subprocess." not in original_lower:
        raise ValueError("introduced subprocess execution")


def apply_patches(
    workspace: Path,
    proposals: list[PatchProposal],
    allowed_files: dict[str, str],
    backups: dict[str, tuple[bytes, int]],
    repair_number: int,
) -> list[AppliedPatch]:
    if len(proposals) > 3:
        raise ValueError("paper code repair exceeds the 3-file patch limit")
    validated = []
    seen = set()
    for proposal in proposals:
        path = _existing_python_path(workspace, proposal.path)
        relative = path.relative_to(workspace).as_posix()
        if relative in seen:
            raise ValueError(f"duplicate paper code patch path {relative}")
        seen.add(relative)
        if relative not in allowed_files:
            raise ValueError(f"paper code patch targets a file outside bounded model context: {relative}")
        content = proposal.content.strip()
        if not content or len(content.encode()) > 256 * 1024:
            raise ValueError(f"paper code patch for {relative} is empty or too large")
        original = allowed_files[relative]
        validate_patch_policy(original, content)
        if original.strip() == content:
            continue
        validated.append((proposal, path, relative, original, content + "\n"))
    if not validated:
        raise ValueError("paper code repair produced no effective patch")
    applied = []
    for proposal, path, relative, original, content in validated:
        if relative not in backups:
            backups[relative] = (path.read_bytes(), path.stat().st_mode)
        _atomic_write(path, content.encode(), path.stat().st_mode)
        applied.append(AppliedPatch(
            repair=repair_number,
            path=relative,
            reason=proposal.reason.strip(),
            before_sha256=_text_sha(original),
            after_sha256=_text_sha(content),
        ))
    return applied


def restore_backups(workspace: Path, backups: dict[str, tuple[bytes, int]]) -> None:
    for relative in sorted(backups):
        path = _existing_python_path(workspace, relative)
        content, mode = backups[relative]
        _atomic_write(path, content, mode)


def source_fingerprint(workspace: str | Path) -> str:
    root = Path(workspace).resolve(strict=True)
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in {".git", ".repropilot", "__pycache__", ".venv", "venv", "node_modules"} for part in relative.parts):
            continue
        if path.is_file() and not path.is_symlink() and path.suffix.lower() in {".py", ".pyi", ".sh"}:
            digest.update(relative.as_posix().encode())
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
    return digest.hexdigest()


def _bounded_python_context(root: Path, entry: Path, max_files: int = 8, max_bytes: int = 256 * 1024, max_per_file: int = 96 * 1024) -> dict[str, str]:
    candidates = [entry] + [path for path in sorted(root.rglob("*.py")) if path != entry]
    result = {}
    used = 0
    for path in candidates:
        if len(result) >= max_files or path.is_symlink() or not path.is_file():
            continue
        resolved = path.resolve(strict=True)
        if root not in resolved.parents:
            continue
        raw = path.read_bytes()
        if len(raw) > max_per_file or used + len(raw) > max_bytes:
            continue
        relative = path.relative_to(root).as_posix()
        result[relative] = raw.decode("utf-8", errors="replace")
        used += len(raw)
    return result


def _existing_python_path(root: Path, value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    if not path.exists() or not path.is_file() or path.is_symlink() or path.suffix.lower() not in {".py", ".pyi"}:
        raise ValueError(f"paper debug path is not an existing regular Python file: {value}")
    resolved = path.resolve(strict=True)
    if root != resolved and root not in resolved.parents:
        raise ValueError("paper debug path escaped workspace")
    return resolved


def _atomic_write(path: Path, content: bytes, mode: int) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=".repropilot-debug-", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _run_record(attempt: int, result: ExecutionResult) -> DebugRun:
    return DebugRun(attempt=attempt, exit_code=result.exit_code, stdout=result.stdout[:8000], stderr=result.stderr[:8000])


def _complete(root: Path, entry: Path, report: DebugReport, metrics: str, mode: str) -> DebugOutcome:
    report.status = "repaired" if report.patches else "passed"
    report.summary = "paper code execution completed"
    report.final_source_fingerprint = source_fingerprint(root)
    report_json = report.model_dump_json()
    patches_json = json.dumps([patch.model_dump(mode="json") for patch in report.patches], ensure_ascii=False)
    artifacts = (
        {"rerun_metrics": metrics, "rerun_report": report_json, "gap_debug_report": report_json, "gap_patch_manifest": patches_json}
        if mode == "fix_and_rerun"
        else {"run_metrics": metrics, "paper_debug_report": report_json, "paper_patch_manifest": patches_json}
    )
    return DebugOutcome(success=True, metrics=metrics, code=entry.read_text(encoding="utf-8"), report=report, artifact_values=artifacts)


def _complete_without_change(
    root: Path,
    entry: Path,
    report: DebugReport,
    metrics: str,
    status: str,
    diagnosis: str,
) -> DebugOutcome:
    report.status = status
    report.summary = diagnosis or f"paper code repair stopped with status {status}"
    report.final_source_fingerprint = source_fingerprint(root)
    report_json = report.model_dump_json()
    artifacts = {
        "rerun_metrics": metrics,
        "rerun_report": report_json,
        "gap_debug_report": report_json,
        "gap_patch_manifest": "[]",
    }
    return DebugOutcome(
        success=True,
        metrics=metrics,
        code=entry.read_text(encoding="utf-8"),
        report=report,
        artifact_values=artifacts,
    )


def _source_snapshot(root: Path) -> dict[str, tuple[bytes, int]]:
    return {
        path.relative_to(root).as_posix(): (path.read_bytes(), path.stat().st_mode)
        for path in _source_files(root)
    }


def _restore_source_snapshot(root: Path, snapshot: dict[str, tuple[bytes, int]]) -> None:
    current = {path.relative_to(root).as_posix(): path for path in _source_files(root)}
    for relative, path in current.items():
        if relative not in snapshot:
            path.unlink(missing_ok=True)
    for relative, (content, mode) in snapshot.items():
        path = root / relative
        if path.is_symlink():
            path.unlink()
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(path, content, mode)


def _source_files(root: Path) -> list[Path]:
    result = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in {".git", ".repropilot", "__pycache__", ".venv", "venv", "node_modules"} for part in relative.parts):
            continue
        if path.is_file() and not path.is_symlink() and path.suffix.lower() in {".py", ".pyi", ".sh"}:
            result.append(path)
    return result


def _text_sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
