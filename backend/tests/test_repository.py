from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from app.repository import (
    build_discovery_query,
    curated_candidates,
    discover_repository,
    materialize_uploaded_files,
    normalize_github_url,
    prepare_first_available_repository,
    prepare_repository,
    repo_prepare_candidate_urls,
    workspace_matches_repo_url,
)


def test_discovery_query_prefers_structured_inputs():
    assert build_discovery_query({"paper_title": "Attention Is All You Need"}, "ignored") == "Attention Is All You Need"
    assert build_discovery_query({"paper_search_query": "transformer paper code", "paper_title": "title"}) == "transformer paper code"


def test_attention_has_trusted_annotated_transformer_candidate():
    candidates = curated_candidates("Attention Is All You Need")
    assert candidates[0]["url"] == "https://github.com/harvardnlp/annotated-transformer"
    assert candidates[0]["trusted"] is True


def test_preferred_repository_bypasses_search():
    result = discover_repository({"preferred_repo_url": "https://github.com/example/research-repo"})
    assert result["repo_url"] == "https://github.com/example/research-repo"
    assert result["repo_validation_report"]["reason"] == "explicit user preference"


def test_candidate_urls_are_normalized_and_deduplicated():
    urls = repo_prepare_candidate_urls(
        "https://github.com/example/repo.git",
        [{"url": "https://github.com/example/repo"}, {"url": "https://github.com/backup/repo"}, {"url": "http://localhost/private"}],
    )
    assert urls == ["https://github.com/example/repo", "https://github.com/backup/repo"]


def test_workspace_remote_match_supports_https_and_ssh(tmp_path):
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text('[remote "origin"]\n  url = git@github.com:harvardnlp/annotated-transformer.git\n', encoding="utf-8")
    assert workspace_matches_repo_url(tmp_path, "https://github.com/harvardnlp/annotated-transformer")
    assert not workspace_matches_repo_url(tmp_path, "https://github.com/example/other")


def test_invalid_repository_urls_are_rejected():
    for value in ("http://localhost/repo", "https://gitlab.com/example/repo", "file:///tmp/repo"):
        with pytest.raises(ValueError):
            normalize_github_url(value)


def test_upload_materialization_checks_hash_and_scope(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = tmp_path / "reviews.csv"
    source.write_text("text,label\na,yes\n", encoding="utf-8")
    checksum = hashlib.sha256(source.read_bytes()).hexdigest()
    result = materialize_uploaded_files(workspace, [{"id": "u1", "name": "reviews.csv", "storage_path": str(source), "sha256": checksum}])
    assert result[0]["path"] == ".repropilot/uploads/01-reviews.csv"
    assert (workspace / result[0]["path"]).read_bytes() == source.read_bytes()


def test_upload_materialization_rejects_workspace_symlink(tmp_path):
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    try:
        os.symlink(outside, workspace / ".repropilot", target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are unavailable on this Windows configuration")
    with pytest.raises(ValueError, match="symlink"):
        materialize_uploaded_files(workspace, [])


@pytest.mark.asyncio
async def test_prepare_repository_clones_into_deterministic_scoped_workspace(tmp_path):
    calls = []

    async def fake_git(command, cwd):
        calls.append((command, cwd))
        target = Path(command[-1])
        (target / ".git").mkdir(parents=True)
        (target / ".git" / "config").write_text('[remote "origin"]\n  url = https://github.com/example/repo.git\n', encoding="utf-8")
        (target / "main.py").write_text("print('ok')\n", encoding="utf-8")

    result = await prepare_repository("https://github.com/example/repo", tmp_path / "workspaces", "plan-1", command_runner=fake_git)
    assert len(calls) == 1
    assert calls[0][0][:5] == ["git", "clone", "--depth", "1", "--"]
    assert Path(result["workspace_path"]).is_dir()
    assert result["repo_manifest"]["repo_url"] == "https://github.com/example/repo"
    assert Path(result["code_file_path"]).name == "main.py"
    assert result["generated_code"] == "print('ok')\n"
    assert json.loads(result["reproduction_mode_report"])["effective_mode"] == "smoke"

    reused = await prepare_repository("https://github.com/example/repo", tmp_path / "workspaces", "plan-1", command_runner=fake_git)
    assert len(calls) == 1
    assert reused["repo_manifest"]["reused_workspace"] is True


@pytest.mark.asyncio
async def test_prepare_tries_trusted_candidates_until_clone_succeeds(tmp_path):
    calls = []

    async def fake_git(command, cwd):
        url = command[-2]
        calls.append(url)
        if url.endswith("/broken"):
            raise RuntimeError("repository unavailable")
        target = Path(command[-1])
        (target / ".git").mkdir(parents=True)
        (target / ".git" / "config").write_text(f'[remote "origin"]\n  url = {url}.git\n', encoding="utf-8")
        (target / "main.py").write_text("print('fallback')\n", encoding="utf-8")

    result = await prepare_first_available_repository(
        "https://github.com/example/broken",
        [{"url": "https://github.com/example/working"}],
        tmp_path / "workspaces",
        "plan-fallback",
        command_runner=fake_git,
    )

    assert calls == ["https://github.com/example/broken", "https://github.com/example/working"]
    assert result["repo_url"] == "https://github.com/example/working"
    assert [attempt["status"] for attempt in result["repo_manifest"]["clone_attempts"]] == ["failed", "ok"]
