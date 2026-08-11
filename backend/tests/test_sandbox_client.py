from __future__ import annotations

import httpx
import pytest

from app.agents import SandboxClient


@pytest.mark.asyncio
async def test_sandbox_client_sends_bearer_token_on_every_operation():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["Authorization"] == "Bearer internal-secret"
        if request.method == "POST" and request.url.path == "/api/v1/sandboxes":
            return httpx.Response(200, json={"sandbox_id": "sandbox-1"})
        if request.method == "DELETE":
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(200, json={"stdout": "ok", "stderr": "", "exit_code": 0})

    client = SandboxClient(
        base_url="https://sandbox.test",
        token="internal-secret",
        transport=httpx.MockTransport(handler),
    )
    sandbox_id = await client.create("")
    assert sandbox_id == "sandbox-1"
    assert (await client.run_python_in(sandbox_id, "print('ok')"))["stdout"] == "ok"
    assert (await client.command(sandbox_id, ["python", "--version"]))["exit_code"] == 0
    await client.delete(sandbox_id)
    assert [request.method for request in requests] == ["POST", "POST", "POST", "DELETE"]

