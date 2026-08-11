from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .reproduction import prepare_reproduction_entry


GITHUB_RE = re.compile(r"^https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$")


def normalize_github_url(value: str) -> str:
    value = value.strip()
    match = GITHUB_RE.match(value)
    if not match:
        raise ValueError("repository URL must be a public GitHub repository")
    owner, repo = match.groups()
    if owner in {".", ".."} or repo in {".", ".."}:
        raise ValueError("invalid GitHub repository path")
    return f"https://github.com/{owner}/{repo}"


def build_discovery_query(inputs: dict[str, Any], parsed_paper: str = "") -> str:
    for key in ("paper_search_query", "paper_title", "paper_method_name", "paper_arxiv_id"):
        value = str(inputs.get(key, "")).strip()
        if value:
            return value
    compact = " ".join(parsed_paper.split())
    return compact[:300] or "paper implementation"


def curated_candidates(query: str) -> list[dict[str, Any]]:
    lowered = query.lower()
    if "attention is all you need" in lowered or "transformer" in lowered or "1706.03762" in lowered:
        return [
            {"url": "https://github.com/harvardnlp/annotated-transformer", "source": "curated", "trusted": True, "score": 0.99},
            {"url": "https://github.com/tensorflow/tensor2tensor", "source": "curated", "trusted": True, "score": 0.9},
        ]
    return []


def discover_repository(inputs: dict[str, Any], parsed_paper: str = "") -> dict[str, Any]:
    preferred = str(inputs.get("preferred_repo_url", "")).strip()
    if preferred:
        url = normalize_github_url(preferred)
        candidate = {"url": url, "source": "user_preferred", "trusted": True, "score": 1.0}
        return {"repo_url": url, "candidate_repositories": [candidate], "repo_validation_report": {"selected": url, "reason": "explicit user preference", "validated": True}}
    query = build_discovery_query(inputs, parsed_paper)
    candidates = curated_candidates(query)
    if not candidates:
        raise ValueError("no trusted repository candidate found; provide a preferred GitHub URL")
    selected = max(candidates, key=lambda item: (bool(item.get("trusted")), float(item.get("score", 0))))
    return {"repo_url": selected["url"], "candidate_repositories": candidates, "repo_validation_report": {"selected": selected["url"], "query": query, "reason": "highest trusted deterministic candidate", "validated": True}}


def repo_prepare_candidate_urls(primary: str, candidates: Any) -> list[str]:
    values = [primary]
    if isinstance(candidates, str):
        try:
            candidates = json.loads(candidates)
        except json.JSONDecodeError:
            candidates = []
    if isinstance(candidates, list):
        for candidate in candidates:
            values.append(str(candidate.get("url", "")) if isinstance(candidate, dict) else str(candidate))
    result = []
    for value in values:
        try:
            normalized = normalize_github_url(value)
        except ValueError:
            continue
        if normalized not in result:
            result.append(normalized)
    return result


def workspace_matches_repo_url(workspace: str | Path, repo_url: str) -> bool:
    root = Path(workspace)
    config = root / ".git" / "config"
    if not config.is_file() or config.is_symlink():
        return False
    try:
        expected = normalize_github_url(repo_url).lower()
    except ValueError:
        return False
    match = re.search(r"^\s*url\s*=\s*(.+?)\s*$", config.read_text(encoding="utf-8", errors="replace"), re.MULTILINE)
    if not match:
        return False
    remote = match.group(1).strip()
    if remote.startswith("git@github.com:"):
        remote = "https://github.com/" + remote.removeprefix("git@github.com:")
    try:
        return normalize_github_url(remote).lower() == expected
    except ValueError:
        return False


def materialize_uploaded_files(workspace: str | Path, uploads: Any) -> list[dict[str, Any]]:
    root = Path(workspace).resolve(strict=True)
    repropilot = root / ".repropilot"
    if repropilot.is_symlink():
        raise ValueError(".repropilot must not be a symlink")
    destination = repropilot / "uploads"
    destination.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink() or root not in destination.resolve(strict=True).parents:
        raise ValueError("upload destination escaped workspace")
    if not isinstance(uploads, list):
        return []
    materialized = []
    for index, item in enumerate(uploads, 1):
        if not isinstance(item, dict):
            continue
        source = Path(str(item.get("storage_path", "")))
        if not source.is_file() or source.is_symlink():
            raise ValueError(f"upload source is not a regular file: {source}")
        name = Path(str(item.get("name") or source.name)).name
        target = destination / f"{index:02d}-{name}"
        shutil.copyfile(source, target)
        checksum = sha256_path(target)
        expected = str(item.get("sha256", "")).strip()
        if expected and checksum.lower() != expected.lower():
            target.unlink(missing_ok=True)
            raise ValueError(f"upload checksum mismatch: {name}")
        materialized.append({"id": item.get("id", ""), "name": name, "path": target.relative_to(root).as_posix(), "sha256": checksum, "size": target.stat().st_size})
    return materialized


def sha256_path(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def repository_manifest(workspace: str | Path, repo_url: str) -> dict[str, Any]:
    root = Path(workspace).resolve(strict=True)
    files = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in {".git", ".repropilot", "node_modules", ".venv", "__pycache__"} for part in relative.parts):
            continue
        if path.is_file() and not path.is_symlink():
            files.append({"path": relative.as_posix(), "size": path.stat().st_size})
        if len(files) >= 500:
            break
    payload = {"repo_url": normalize_github_url(repo_url), "workspace": str(root), "files": files}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    payload["fingerprint"] = hashlib.sha256(canonical.encode()).hexdigest()
    return payload


async def prepare_repository(
    repo_url: str,
    workspace_root: str | Path,
    plan_id: str,
    uploads: Any = None,
    command_runner=None,
    reproduction_inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = normalize_github_url(repo_url)
    root = Path(workspace_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    slug = hashlib.sha256(f"{plan_id}\0{url}".encode()).hexdigest()[:16]
    target = root / slug
    if root not in target.resolve().parents:
        raise ValueError("repository workspace escaped configured root")
    reused = False
    if target.exists():
        if not target.is_dir() or target.is_symlink() or not workspace_matches_repo_url(target, url):
            raise ValueError("existing workspace does not match requested repository")
        reused = True
    else:
        runner = command_runner or _run_git
        await runner(["git", "clone", "--depth", "1", "--", url, str(target)], root)
        if not workspace_matches_repo_url(target, url):
            raise ValueError("cloned workspace remote does not match requested repository")
    materialized = materialize_uploaded_files(target, uploads or [])
    entry = prepare_reproduction_entry(target, {**(reproduction_inputs or {}), "repo_url": url})
    manifest = repository_manifest(target, url)
    manifest["materialized_uploads"] = materialized
    manifest["reused_workspace"] = reused
    manifest["selected_code_file"] = Path(entry.selected_code_file).relative_to(target).as_posix() if entry.selected_code_file else ""
    manifest["dependency_files"] = entry.dependency_files
    manifest["code_file_candidates"] = entry.code_file_candidates
    manifest["repro_entry_kind"] = entry.repro_entry_kind
    manifest["reproduction_mode"] = entry.mode_decision.effective_mode
    manifest["full_reproduction_switch"] = entry.mode_decision.effective_mode == "full"
    manifest["mode_decision"] = entry.mode_decision.model_dump(mode="json")
    return {
        "workspace_path": str(target.resolve()),
        "repo_url": url,
        "repo_manifest": manifest,
        "materialized_uploads": materialized,
        "code_file_path": entry.selected_code_file,
        "generated_code": Path(entry.selected_code_file).read_text(encoding="utf-8", errors="replace") if entry.selected_code_file else "",
        "reproduction_mode_report": entry.mode_decision.model_dump_json(indent=2),
    }


async def prepare_first_available_repository(
    primary_url: str,
    candidates: Any,
    workspace_root: str | Path,
    plan_id: str,
    uploads: Any = None,
    command_runner=None,
    reproduction_inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    urls = repo_prepare_candidate_urls(primary_url, candidates)[:5]
    if not urls:
        raise ValueError("repo_prepare has no valid GitHub clone candidate")
    attempts: list[dict[str, str]] = []
    for url in urls:
        try:
            prepared = await prepare_repository(
                url,
                workspace_root,
                plan_id,
                uploads,
                command_runner,
                reproduction_inputs,
            )
            attempts.append({"url": url, "status": "ok"})
            prepared["repo_manifest"]["clone_attempts"] = attempts
            return prepared
        except Exception as exc:
            attempts.append({"url": url, "status": "failed", "error": str(exc)[:1000]})
    raise RuntimeError(f"clone repo failed after {len(attempts)} candidate(s): {json.dumps(attempts, ensure_ascii=False)}")


async def _run_git(command: list[str], cwd: Path) -> None:
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=300)
    if process.returncode != 0:
        raise RuntimeError(f"git clone failed: {(stderr or stdout).decode('utf-8', errors='replace')[:2000]}")
