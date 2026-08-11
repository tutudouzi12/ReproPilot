from __future__ import annotations

import json
import shutil
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SANDBOX_URL = "http://127.0.0.1:8082/api/v1"
SANDBOX_TOKEN = "local-sandbox-token"


def request_json(method: str, url: str, payload: dict | None = None, *, authorized: bool = True) -> tuple[int, dict]:
    headers = {"Content-Type": "application/json"}
    if authorized:
        headers["Authorization"] = f"Bearer {SANDBOX_TOKEN}"
    data = json.dumps(payload).encode() if payload is not None else None
    request = Request(url, method=method, data=data, headers=headers)
    try:
        with urlopen(request, timeout=45) as response:
            return response.status, json.load(response)
    except HTTPError as exc:
        body = json.loads(exc.read().decode("utf-8"))
        return exc.code, body


def wait_for_health(url: str, attempts: int = 60) -> None:
    for _ in range(attempts):
        try:
            with urlopen(url, timeout=3) as response:
                if response.status == 200:
                    return
        except (HTTPError, URLError, TimeoutError):
            pass
        time.sleep(1)
    raise RuntimeError(f"health check did not become ready: {url}")


def docker_inspect(sandbox_id: str) -> dict:
    completed = subprocess.run(
        ["docker", "inspect", sandbox_id],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(completed.stdout)[0]


def assert_no_sandbox_containers() -> None:
    completed = subprocess.run(
        ["docker", "ps", "-aq", "--filter", "label=repropilot.sandbox=true"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert not completed.stdout.strip(), f"sandbox containers leaked: {completed.stdout.strip()}"


def main() -> None:
    if not shutil.which("docker"):
        raise RuntimeError("docker CLI is required")

    for health_url in (
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8080/api/health",
        f"{SANDBOX_URL}/health",
    ):
        wait_for_health(health_url)

    status, _ = request_json("POST", f"{SANDBOX_URL}/sandboxes", {"image": "python:3.11-slim"}, authorized=False)
    assert status == 401, f"sandbox accepted an unauthenticated request: {status}"

    status, _ = request_json("POST", f"{SANDBOX_URL}/sandboxes", {"image": "ubuntu:latest"})
    assert status == 500, f"sandbox accepted a non-allowlisted image: {status}"

    status, _ = request_json(
        "POST",
        f"{SANDBOX_URL}/sandboxes",
        {"image": "python:3.11-slim", "mount_path": "/etc"},
    )
    assert status == 500, f"sandbox accepted a mount outside its roots: {status}"

    sandbox_id = ""
    try:
        status, created = request_json("POST", f"{SANDBOX_URL}/sandboxes", {"image": "repropilot-sandbox-runtime:latest"})
        assert status == 200, created
        sandbox_id = created["sandbox_id"]

        inspected = docker_inspect(sandbox_id)
        config = inspected["Config"]
        host = inspected["HostConfig"]
        assert config["NetworkDisabled"] is True
        assert host["Memory"] == 512 * 1024 * 1024
        assert host["NanoCpus"] == 1_000_000_000
        assert host["PidsLimit"] == 128
        assert host["CapDrop"] == ["ALL"]
        assert "no-new-privileges:true" in host["SecurityOpt"]

        status, executed = request_json(
            "POST",
            f"{SANDBOX_URL}/sandboxes/{sandbox_id}/python",
            {
                "code": (
                    "import json, torch\n"
                    "print(json.dumps({'sum': sum(range(11)), 'torch': torch.__version__}))"
                )
            },
        )
        scientific = json.loads(executed["stdout"])
        assert status == 200 and executed["exit_code"] == 0 and scientific["sum"] == 55, executed
        assert scientific["torch"].startswith("2.13.0"), scientific

        status, network = request_json(
            "POST",
            f"{SANDBOX_URL}/sandboxes/{sandbox_id}/python",
            {"code": "import urllib.request; urllib.request.urlopen('https://example.com', timeout=3)"},
        )
        assert status == 200 and network["exit_code"] != 0, network

        status, timeout = request_json(
            "POST",
            f"{SANDBOX_URL}/sandboxes/{sandbox_id}/commands",
            {"cmd": ["sh", "-c", "timeout 1s sleep 5"]},
        )
        assert status == 200 and timeout["timed_out"] is True and timeout["exit_code"] == 124, timeout

        status, truncated = request_json(
            "POST",
            f"{SANDBOX_URL}/sandboxes/{sandbox_id}/python",
            {"code": "print('x' * 1100000)"},
        )
        output = truncated["stdout"]
        assert status == 200 and truncated["exit_code"] == 0
        assert "[truncated " in output and len(output.encode("utf-8")) <= 1_048_576
    finally:
        if sandbox_id:
            request_json("DELETE", f"{SANDBOX_URL}/sandboxes/{sandbox_id}")

    assert_no_sandbox_containers()
    print("Docker smoke: PASS (health, auth, isolation, limits, execution, timeout, truncation, cleanup)")


if __name__ == "__main__":
    main()
