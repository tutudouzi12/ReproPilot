from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "run_repository_benchmark_replay.py"
SPEC = importlib.util.spec_from_file_location("repository_benchmark_replay", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
repository_benchmark_replay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(repository_benchmark_replay)


def test_checked_in_replay_selects_python_node_and_maven_tasks() -> None:
    manifest = ROOT / "examples" / "autoresearch" / "repository-scale" / "replay.json"

    payload, benchmark, tasks = repository_benchmark_replay.load_replay(manifest)

    assert payload["id"] == "repository-scale-cross-runtime-replay-v1"
    assert benchmark["id"] == "repository-scale-pilot-v1"
    assert [task["id"] for task in tasks] == [
        "flask-ipv6-host-parsing",
        "p-queue-abort-listener-cleanup",
        "commons-codec-phonetic-boundaries",
    ]
    assert [task["setup"]["kind"] for task in tasks] == ["python_venv", "npm", "maven"]


def test_replay_workflow_installs_harness_before_running_replay() -> None:
    workflow = ROOT / ".github" / "workflows" / "repository-benchmark-replay.yml"
    text = workflow.read_text(encoding="utf-8")

    install = "python -m pip install --disable-pip-version-check --no-input --editable ./backend"
    assert install in text
    assert text.index(install) < text.index("python scripts/run_repository_benchmark_replay.py")
    assert "uses: actions/setup-java@v5" in text
    assert 'java-version: "8"' in text
    assert text.index("uses: actions/setup-java@v5") < text.index("python scripts/run_repository_benchmark_replay.py")
    assert "uses: actions/upload-artifact@v7" in text


@pytest.mark.parametrize(
    ("setup", "message"),
    [
        (
            {
                "kind": "python_venv",
                "python_version": "3.11",
                "editable_checkout": True,
                "packages": ["--index-url=https://example.invalid"],
            },
            "non-exact or unsafe",
        ),
        (
            {
                "kind": "npm",
                "node_major": 22,
                "package_lock": False,
                "packages": ["sample@latest"],
            },
            "non-exact or unsafe",
        ),
    ],
)
def test_setup_contract_rejects_flags_and_unpinned_packages(setup: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        repository_benchmark_replay.validate_setup("sample", setup)


@pytest.mark.parametrize(
    "setup",
    [
        {
            "kind": "python_venv",
            "python_version": "3.11",
            "editable_checkout": True,
            "packages": ["pytest==9.1.1"],
            "command": "python arbitrary.py",
        },
        {
            "kind": "npm",
            "node_major": 22,
            "package_lock": False,
            "packages": ["tsx@4.23.12"],
            "command": "npm run arbitrary",
        },
        {"kind": "maven", "java_major": 8, "maven_major": 3, "command": "mvn arbitrary"},
    ],
)
def test_setup_contract_rejects_unknown_command_fields(setup: dict) -> None:
    with pytest.raises(ValueError, match="unsupported fields: command"):
        repository_benchmark_replay.validate_setup("sample", setup)


@pytest.mark.parametrize(
    ("setup", "message"),
    [
        ({"kind": "maven", "java_major": 7, "maven_major": 3}, "supported Java major"),
        ({"kind": "maven", "java_major": 8, "maven_major": 4}, "Maven major 3"),
    ],
)
def test_maven_setup_rejects_unsupported_toolchain(setup: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        repository_benchmark_replay.validate_setup("sample", setup)


def test_python_setup_builds_an_argument_list_without_shell(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[tuple[str, list[str]]] = []

    def fake_run_stage(stage, command, cwd, workspace, records, timeout_seconds):
        calls.append((stage, command))
        return {"exit_code": 0, "duration_ms": 1, "stdout": "", "stderr": ""}

    monkeypatch.setattr(repository_benchmark_replay, "run_stage", fake_run_stage)
    task = {
        "id": "sample-python",
        "setup": {
            "kind": "python_venv",
            "python_version": f"{repository_benchmark_replay.sys.version_info.major}.{repository_benchmark_replay.sys.version_info.minor}",
            "editable_checkout": True,
            "packages": ["pytest==9.1.1"],
        },
    }
    checkout = tmp_path / "checkout"

    python, _ = repository_benchmark_replay.prepare_runtime(task, checkout, tmp_path, [])

    assert python == repository_benchmark_replay.venv_python(tmp_path / "venvs" / "sample-python")
    assert [stage for stage, _ in calls] == ["python_venv", "python_dependencies"]
    assert calls[1][1][-2:] == [str(checkout), "pytest==9.1.1"]
    assert "--editable" in calls[1][1]


def test_npm_setup_uses_pinned_packages_and_disables_scripts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[str, list[str]]] = []

    def fake_run_stage(stage, command, cwd, workspace, records, timeout_seconds):
        calls.append((stage, command))
        stdout = "v22.23.1\n" if stage == "node_version" else ""
        return {"exit_code": 0, "duration_ms": 1, "stdout": stdout, "stderr": ""}

    monkeypatch.setattr(repository_benchmark_replay, "run_stage", fake_run_stage)
    monkeypatch.setattr(repository_benchmark_replay.shutil, "which", lambda name: f"/tools/{name}")
    task = {
        "id": "sample-node",
        "setup": {
            "kind": "npm",
            "node_major": 22,
            "package_lock": False,
            "packages": ["tsx@4.23.12"],
        },
    }

    _, runtime = repository_benchmark_replay.prepare_runtime(task, tmp_path / "checkout", tmp_path, [])

    assert runtime["node"] == "22.23.1"
    assert [stage for stage, _ in calls] == ["node_version", "npm_dependencies"]
    assert "--ignore-scripts" in calls[1][1]
    assert "--package-lock=false" in calls[1][1]
    assert calls[1][1][-1] == "tsx@4.23.12"


def test_maven_setup_validates_and_records_fixed_tool_commands(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[str, list[str]]] = []

    def fake_run_stage(stage, command, cwd, workspace, records, timeout_seconds):
        calls.append((stage, command))
        outputs = {
            "java_version": {"stdout": "", "stderr": 'openjdk version "1.8.0_442"\n'},
            "javac_version": {"stdout": "javac 1.8.0_442\n", "stderr": ""},
            "maven_version": {"stdout": "Apache Maven 3.9.9\n", "stderr": ""},
        }
        return {"exit_code": 0, "duration_ms": 1, **outputs[stage]}

    monkeypatch.setattr(repository_benchmark_replay, "run_stage", fake_run_stage)
    monkeypatch.setattr(repository_benchmark_replay.shutil, "which", lambda name: f"/tools/{name}")
    task = {
        "id": "sample-maven",
        "setup": {"kind": "maven", "java_major": 8, "maven_major": 3},
    }

    python, runtime = repository_benchmark_replay.prepare_runtime(task, tmp_path / "checkout", tmp_path, [])

    assert python == Path(repository_benchmark_replay.sys.executable)
    assert [stage for stage, _ in calls] == ["java_version", "javac_version", "maven_version"]
    assert [command[1:] for _, command in calls] == [["-version"], ["-version"], ["-version"]]
    assert runtime == {
        "python": f"{repository_benchmark_replay.sys.version_info.major}.{repository_benchmark_replay.sys.version_info.minor}",
        "node": "",
        "java": "1.8.0_442",
        "javac": "1.8.0_442",
        "maven": "3.9.9",
    }


def test_retained_commands_replace_runtime_executable_paths(tmp_path: Path) -> None:
    result = {"exit_code": 0, "duration_ms": 1, "stdout": "", "stderr": ""}

    python_record = repository_benchmark_replay.retained_command(
        [str(Path(repository_benchmark_replay.sys.executable)), "-m", "venv", str(tmp_path / "venv")],
        tmp_path,
        result,
        tmp_path,
    )
    node_record = repository_benchmark_replay.retained_command(
        [str(Path(repository_benchmark_replay.sys.executable).with_name("node.exe")), "--version"],
        tmp_path,
        result,
        tmp_path,
    )
    java_record = repository_benchmark_replay.retained_command(
        [str(Path(repository_benchmark_replay.sys.executable).with_name("java.exe")), "-version"],
        tmp_path,
        result,
        tmp_path,
    )
    javac_record = repository_benchmark_replay.retained_command(
        [str(Path(repository_benchmark_replay.sys.executable).with_name("javac.exe")), "-version"],
        tmp_path,
        result,
        tmp_path,
    )
    maven_record = repository_benchmark_replay.retained_command(
        [str(Path(repository_benchmark_replay.sys.executable).with_name("mvn.cmd")), "-version"],
        tmp_path,
        result,
        tmp_path,
    )

    assert python_record["command"][0] == "{python}"
    assert node_record["command"][0] == "{node}"
    assert java_record["command"][0] == "{java}"
    assert javac_record["command"][0] == "{javac}"
    assert maven_record["command"][0] == "{maven}"
    assert str(tmp_path) not in json.dumps([python_record, node_record, java_record, javac_record, maven_record])


def test_runtime_validation_failure_is_classified_as_setup_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    monkeypatch.setattr(repository_benchmark_replay, "prepare_checkout", lambda task, workspace, records: checkout)

    def fail_runtime(task, checkout, workspace, records):
        raise ValueError("Java 8 is required, found 17.0.12")

    monkeypatch.setattr(repository_benchmark_replay, "prepare_runtime", fail_runtime)
    task = {
        "id": "sample-maven",
        "setup": {"kind": "maven", "java_major": 8, "maven_major": 3},
        "task": {"repository": {"url": "https://github.com/example/project.git", "revision": "a" * 40}},
    }

    result = repository_benchmark_replay.replay_task(task, tmp_path)

    assert result["status"] == "setup_failed"
    assert result["failed_stage"] == "runtime_validation"
    assert result["error_type"] == "ValueError"
    assert result["preflight"] is None


def test_checkout_retries_transient_clone_in_separate_directories(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clone_attempts = 0

    def fake_command_result(command, cwd, timeout_seconds):
        nonlocal clone_attempts
        if command[:2] == ["git", "clone"]:
            clone_attempts += 1
            return {
                "exit_code": 128 if clone_attempts == 1 else 0,
                "duration_ms": 1,
                "stdout": "",
                "stderr": "TLS connect error" if clone_attempts == 1 else "",
            }
        return {"exit_code": 0, "duration_ms": 1, "stdout": "", "stderr": ""}

    monkeypatch.setattr(repository_benchmark_replay, "command_result", fake_command_result)
    monkeypatch.setattr(repository_benchmark_replay.time, "sleep", lambda _seconds: None)
    task = {
        "id": "sample",
        "task": {"repository": {"url": "https://github.com/example/project.git", "revision": "a" * 40}},
    }
    records: list[dict] = []

    checkout = repository_benchmark_replay.prepare_checkout(task, tmp_path, records)

    assert checkout.name == repository_benchmark_replay.checkout_directory_name("sample", 2)
    assert len(checkout.name) == 14
    assert clone_attempts == 2
    assert [record["attempt"] for record in records if record["stage"] == "clone"] == [1, 2]
    assert records[0]["stderr_tail"] == "TLS connect error"


def test_main_failure_artifact_does_not_retain_workspace_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    output = tmp_path / "artifact.json"
    workspace = tmp_path / "occupied"
    workspace.mkdir()
    (workspace / "file").write_text("occupied", encoding="utf-8")
    manifest = ROOT / "examples" / "autoresearch" / "repository-scale" / "replay.json"
    monkeypatch.setattr(
        repository_benchmark_replay,
        "parse_args",
        lambda: type("Args", (), {"manifest": manifest, "workspace": workspace, "output": output})(),
    )

    with pytest.raises(SystemExit):
        repository_benchmark_replay.main()

    artifact = json.loads(output.read_text(encoding="utf-8"))
    assert artifact["status"] == "manifest_or_workspace_failed"
    assert str(workspace) not in artifact["error"]
    assert "{replay_workspace}" in artifact["error"]
