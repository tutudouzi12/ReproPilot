from __future__ import annotations

import json

from fastapi.testclient import TestClient
import pytest

import app.main as main


class FakeEngine:
    def __init__(self) -> None:
        self.removed: list[str] = []

    def health(self) -> dict:
        return {"available": True, "version": "fake"}

    def create(self, image: str, mount_path: str) -> str:
        assert image == "python:3.11-slim"
        return "sandbox-1"

    def remove(self, sandbox_id: str) -> None:
        self.removed.append(sandbox_id)

    def run(self, sandbox_id: str, command: list[str]) -> dict:
        assert sandbox_id == "sandbox-1"
        return {"stdout": "ok\n", "stderr": "", "exit_code": 0, "images": []}


def test_sandbox_lifecycle(monkeypatch):
    fake = FakeEngine()
    monkeypatch.setattr(main, "engine", fake)
    client = TestClient(main.app)

    assert client.get("/api/v1/health").json()["runtime"] == "python"
    created = client.post("/api/v1/sandboxes", json={"image": "python:3.11-slim"})
    assert created.status_code == 200
    sandbox_id = created.json()["sandbox_id"]

    executed = client.post(
        f"/api/v1/sandboxes/{sandbox_id}/python",
        json={"code": "print('ok')"},
    )
    assert executed.status_code == 200
    assert executed.json()["stdout"] == "ok\n"

    streamed = client.post(
        f"/api/v1/sandboxes/{sandbox_id}/python/stream",
        json={"code": "print('ok')"},
    )
    assert streamed.status_code == 200
    assert '"type": "chunk"' in streamed.text
    assert '"type": "final"' in streamed.text

    deleted = client.delete(f"/api/v1/sandboxes/{sandbox_id}")
    assert deleted.status_code == 200
    assert fake.removed == [sandbox_id]


def test_bearer_token_is_enforced(monkeypatch):
    monkeypatch.setattr(main, "engine", FakeEngine())
    monkeypatch.setenv("SANDBOX_API_TOKEN", "secret")
    client = TestClient(main.app)
    denied = client.post("/api/v1/sandboxes", json={"image": "python:3.11-slim"})
    assert denied.status_code == 401
    allowed = client.post(
        "/api/v1/sandboxes",
        json={"image": "python:3.11-slim"},
        headers={"Authorization": "Bearer secret"},
    )
    assert allowed.status_code == 200


def test_docker_create_applies_allowlists_and_security_limits(tmp_path, monkeypatch):
    class Container:
        id = "container-1"

        def start(self):
            return None

    class Containers:
        def __init__(self):
            self.kwargs = None

        def create(self, image, **kwargs):
            self.kwargs = {"image": image, **kwargs}
            return Container()

    class Client:
        def __init__(self):
            self.containers = Containers()

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("SANDBOX_WORKSPACE_ROOTS", str(tmp_path))
    monkeypatch.setenv("SANDBOX_IMAGE_ALLOWLIST", "python:3.11-slim")
    monkeypatch.setenv("SANDBOX_MEMORY_LIMIT", "768m")
    monkeypatch.setenv("SANDBOX_CPU_LIMIT", "1.5")
    monkeypatch.setenv("SANDBOX_PIDS_LIMIT", "64")
    engine = main.DockerEngine()
    engine._client = Client()

    sandbox_id = engine.create("python:3.11-slim", str(workspace))

    options = engine._client.containers.kwargs
    assert sandbox_id == "container-1"
    assert options["network_disabled"] is True
    assert options["mem_limit"] == "768m"
    assert options["nano_cpus"] == 1_500_000_000
    assert options["pids_limit"] == 64
    assert options["cap_drop"] == ["ALL"]
    assert options["security_opt"] == ["no-new-privileges:true"]
    assert options["device_requests"] is None
    assert options["volumes"][str(workspace.resolve())]["bind"] == "/workspace"

    with pytest.raises(ValueError, match="image is not allowed"):
        engine.create("evil/image:latest", str(workspace))
    with pytest.raises(ValueError, match="outside allowed"):
        engine.create("python:3.11-slim", str(tmp_path.parent))


def test_gpu_device_request_supports_all_and_specific_devices(monkeypatch):
    monkeypatch.setenv("SANDBOX_DOCKER_GPUS", " all ")
    request = main.gpu_device_requests()[0]
    assert request["Count"] == -1
    assert request["Capabilities"] == [["gpu"]]

    monkeypatch.setenv("SANDBOX_DOCKER_GPUS", "device=0, 2")
    request = main.gpu_device_requests()[0]
    assert request["DeviceIDs"] == ["0", "2"]

    monkeypatch.setenv("SANDBOX_DOCKER_GPUS", "none")
    assert main.gpu_device_requests() == []


def test_output_truncation_preserves_head_tail_and_utf8_boundary():
    value = "开头-" + ("数据" * 200) + "-结尾"
    truncated = main.truncate_output(value, 128)
    assert truncated.startswith("开头")
    assert truncated.endswith("结尾")
    assert "truncated" in truncated
    assert len(truncated.encode("utf-8")) <= 132


def test_ndjson_preserves_empty_lines_and_always_finishes_with_final_event():
    events = [json.loads(line) for line in main.ndjson_result({
        "stdout": "line-1\n\nline-2\n",
        "stderr": "",
        "exit_code": 0,
        "images": [],
    })]
    assert [event["message"] for event in events[:-1]] == ["line-1", "", "line-2"]
    assert events[-1]["type"] == "final"

    failed = [json.loads(line) for line in main.ndjson_execution(lambda: (_ for _ in ()).throw(RuntimeError("boom")))]
    assert failed[0] == {"type": "chunk", "stream": "stderr", "message": "boom"}
    assert failed[-1]["type"] == "final"
    assert failed[-1]["response"]["exit_code"] == -1


def test_docker_run_applies_execution_timeout_and_reports_timeout(monkeypatch):
    class Result:
        exit_code = 124
        output = (b"partial", b"")

    class Container:
        command = None

        def exec_run(self, command, demux):
            assert demux is True
            self.command = command
            return Result()

    class Containers:
        container = Container()

        def get(self, sandbox_id):
            assert sandbox_id == "sandbox-1"
            return self.container

    class Client:
        containers = Containers()

    monkeypatch.setenv("SANDBOX_EXEC_TIMEOUT_SECONDS", "7")
    engine = main.DockerEngine()
    engine._client = Client()
    result = engine.run("sandbox-1", ["python", "-c", "while True: pass"])

    assert engine._client.containers.container.command[:3] == ["timeout", "--signal=KILL", "7s"]
    assert result["timed_out"] is True
    assert result["exit_code"] == 124
    assert "timed out after 7 seconds" in result["stderr"]
