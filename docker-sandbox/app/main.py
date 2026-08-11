from __future__ import annotations

import hmac
import json
import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Protocol

import docker
from docker.errors import DockerException, NotFound
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field


class CreateRequest(BaseModel):
    image: str = "python:3.11-slim"
    mount_path: str = ""


class CodeRequest(BaseModel):
    code: str = Field(min_length=1, max_length=200_000)


class CommandRequest(BaseModel):
    cmd: list[str] = Field(min_length=1, max_length=32)


class SandboxEngine(Protocol):
    def health(self) -> dict: ...
    def create(self, image: str, mount_path: str) -> str: ...
    def remove(self, sandbox_id: str) -> None: ...
    def run(self, sandbox_id: str, command: list[str]) -> dict: ...


class DockerEngine:
    def __init__(self) -> None:
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = docker.from_env()
        return self._client

    def health(self) -> dict:
        try:
            version = self.client.version()
            return {
                "available": True,
                "version": version.get("Version", "unknown"),
                "gpu_request": configured_gpu_request() or "none",
            }
        except DockerException as exc:
            return {"available": False, "error": str(exc)}

    def create(self, image: str, mount_path: str) -> str:
        allowed_images = {
            item.strip() for item in os.getenv("SANDBOX_IMAGE_ALLOWLIST", "python:3.11-slim,python:3.12-slim").split(",")
        }
        if image not in allowed_images:
            raise ValueError(f"image is not allowed: {image}")
        volumes = None
        if mount_path:
            resolved = Path(mount_path).resolve()
            roots = [Path(item).resolve() for item in os.getenv("SANDBOX_WORKSPACE_ROOTS", "/tmp").split(os.pathsep)]
            if not any(resolved == root or root in resolved.parents for root in roots):
                raise ValueError("mount path is outside allowed workspace roots")
            volumes = {str(resolved): {"bind": "/workspace", "mode": "rw"}}
        container = self.client.containers.create(
            image,
            command=["sleep", "infinity"],
            detach=True,
            working_dir="/workspace" if volumes else "/tmp",
            network_disabled=os.getenv("SANDBOX_NETWORK_DISABLED", "true").lower() == "true",
            mem_limit=os.getenv("SANDBOX_MEMORY_LIMIT", "512m"),
            nano_cpus=int(float(os.getenv("SANDBOX_CPU_LIMIT", "1")) * 1_000_000_000),
            pids_limit=int(os.getenv("SANDBOX_PIDS_LIMIT", "128")),
            cap_drop=["ALL"],
            security_opt=["no-new-privileges:true"],
            device_requests=gpu_device_requests() or None,
            volumes=volumes,
            labels={"repropilot.sandbox": "true"},
        )
        container.start()
        return container.id

    def remove(self, sandbox_id: str) -> None:
        try:
            self.client.containers.get(sandbox_id).remove(force=True)
        except NotFound:
            return

    def run(self, sandbox_id: str, command: list[str]) -> dict:
        container = self.client.containers.get(sandbox_id)
        timeout_seconds = max(1, int(os.getenv("SANDBOX_EXEC_TIMEOUT_SECONDS", "300")))
        bounded_command = ["timeout", "--signal=KILL", f"{timeout_seconds}s", *command]
        result = container.exec_run(bounded_command, demux=True)
        stdout, stderr = result.output if isinstance(result.output, tuple) else (result.output, b"")
        limit = max(1024, int(os.getenv("SANDBOX_MAX_OUTPUT_BYTES", str(1024 * 1024))))
        timed_out = result.exit_code in {124, 137}
        stderr_text = (stderr or b"").decode("utf-8", errors="replace")
        if timed_out and not stderr_text.strip():
            stderr_text = f"execution timed out after {timeout_seconds} seconds"
        return {
            "stdout": truncate_output((stdout or b"").decode("utf-8", errors="replace"), limit),
            "stderr": truncate_output(stderr_text, limit),
            "exit_code": result.exit_code,
            "timed_out": timed_out,
            "images": [],
        }


engine: SandboxEngine = DockerEngine()
app = FastAPI(title="ReproPilot Python Sandbox", version="0.1.0")


def configured_gpu_request() -> str:
    value = os.getenv("SANDBOX_DOCKER_GPUS", "").strip()
    return "" if value.lower() in {"", "none", "false", "0"} else value


def gpu_device_requests() -> list[docker.types.DeviceRequest]:
    value = configured_gpu_request()
    if not value:
        return []
    if value.lower() == "all":
        return [docker.types.DeviceRequest(count=-1, capabilities=[["gpu"]])]
    if value.lower().startswith("device="):
        value = value.split("=", 1)[1]
    device_ids = [item.strip() for item in value.split(",") if item.strip()]
    if not device_ids:
        raise ValueError("SANDBOX_DOCKER_GPUS must be 'all' or a comma-separated device list")
    return [docker.types.DeviceRequest(device_ids=device_ids, capabilities=[["gpu"]])]


def truncate_output(value: str, max_bytes: int) -> str:
    raw = value.encode("utf-8")
    if len(raw) <= max_bytes:
        return value
    marker = f"\n... [truncated {len(raw) - max_bytes} bytes] ...\n".encode()
    available = max(0, max_bytes - len(marker))
    head_size = available // 2
    tail_size = available - head_size
    head = raw[:head_size].decode("utf-8", errors="ignore")
    tail = raw[-tail_size:].decode("utf-8", errors="ignore") if tail_size else ""
    return head + marker.decode("utf-8") + tail


def authorize(authorization: str | None = Header(default=None)) -> None:
    expected = os.getenv("SANDBOX_API_TOKEN", "").strip()
    if not expected:
        return
    provided = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="invalid sandbox bearer token")


@app.get("/api/v1/health")
def health() -> dict:
    status = engine.health()
    return {"ok": status.get("available", False), "native_docker": status, "runtime": "python"}


@app.post("/api/v1/sandboxes", dependencies=[Depends(authorize)])
def create_sandbox(payload: CreateRequest) -> dict[str, str]:
    try:
        return {"sandbox_id": engine.create(payload.image, payload.mount_path)}
    except (DockerException, ValueError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.delete("/api/v1/sandboxes/{sandbox_id}", dependencies=[Depends(authorize)])
def delete_sandbox(sandbox_id: str) -> dict[str, bool]:
    engine.remove(sandbox_id)
    return {"ok": True}


@app.post("/api/v1/sandboxes/{sandbox_id}/python", dependencies=[Depends(authorize)])
def execute_python(sandbox_id: str, payload: CodeRequest) -> dict:
    return engine.run(sandbox_id, ["python", "-I", "-c", payload.code])


@app.post("/api/v1/sandboxes/{sandbox_id}/commands", dependencies=[Depends(authorize)])
def execute_command(sandbox_id: str, payload: CommandRequest) -> dict:
    return engine.run(sandbox_id, payload.cmd)


def ndjson_result(result: dict) -> Iterator[str]:
    stdout = result.get("stdout", "")
    stderr = result.get("stderr", "")

    def lines(value: str) -> list[str]:
        if value == "":
            return []
        parts = value.split("\n")
        if value.endswith("\n"):
            parts.pop()
        return parts

    for line in lines(stdout):
        yield json.dumps({"type": "chunk", "stream": "stdout", "message": line}, ensure_ascii=False) + "\n"
    for line in lines(stderr):
        yield json.dumps({"type": "chunk", "stream": "stderr", "message": line}, ensure_ascii=False) + "\n"
    yield json.dumps({"type": "final", "response": result}, ensure_ascii=False) + "\n"


def ndjson_execution(execute: Callable[[], dict]) -> Iterator[str]:
    try:
        result = execute()
    except Exception as exc:
        result = {"stdout": "", "stderr": str(exc), "exit_code": -1, "timed_out": False, "images": []}
    yield from ndjson_result(result)


@app.post("/api/v1/sandboxes/{sandbox_id}/python/stream", dependencies=[Depends(authorize)])
def stream_python(sandbox_id: str, payload: CodeRequest) -> StreamingResponse:
    return StreamingResponse(
        ndjson_execution(lambda: execute_python(sandbox_id, payload)),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/v1/sandboxes/{sandbox_id}/commands/stream", dependencies=[Depends(authorize)])
def stream_command(sandbox_id: str, payload: CommandRequest) -> StreamingResponse:
    return StreamingResponse(
        ndjson_execution(lambda: execute_command(sandbox_id, payload)),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
