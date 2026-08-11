from __future__ import annotations

import socket

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app.main as main


def test_api_bearer_token_protects_routes_but_not_health(monkeypatch):
    monkeypatch.setenv("API_AUTH_TOKEN", "test-secret")
    client = TestClient(main.app)
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/hello").status_code == 401
    allowed = client.get("/api/hello", headers={"Authorization": "Bearer test-secret"})
    assert allowed.status_code == 200


def test_pdf_url_rejects_non_arxiv_and_private_resolution(monkeypatch):
    with pytest.raises(HTTPException):
        main.validate_remote_pdf_url("http://127.0.0.1/secret.pdf")
    with pytest.raises(HTTPException):
        main.validate_remote_pdf_url("https://arxiv.org.evil.example/paper.pdf")

    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))])
    with pytest.raises(HTTPException, match="non-public"):
        main.validate_remote_pdf_url("https://arxiv.org/pdf/1706.03762")


def test_pdf_url_accepts_public_arxiv_address(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("151.101.3.42", 443))])
    main.validate_remote_pdf_url("https://arxiv.org/pdf/1706.03762")


def test_cors_allows_identity_headers_for_configured_origin():
    client = TestClient(main.app)
    response = client.options(
        "/api/plan",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "X-User-Id,X-Session-Id,Content-Type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    allowed = response.headers["access-control-allow-headers"].lower()
    assert "x-user-id" in allowed
    assert "x-session-id" in allowed
    assert response.headers["access-control-allow-credentials"] == "true"


def test_cors_does_not_grant_unknown_origin():
    client = TestClient(main.app)
    response = client.options(
        "/api/plan",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.asyncio
async def test_backend_health_checks_real_sandbox_and_sends_token():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/health"
        assert request.headers["Authorization"] == "Bearer sandbox-secret"
        return httpx.Response(200, json={"ok": True, "runtime": "python", "native_docker": {"available": True}})

    status = await main.fetch_sandbox_health(
        "https://sandbox.test",
        "sandbox-secret",
        httpx.MockTransport(handler),
    )
    assert status["ok"] is True
    assert status["native_docker"]["available"] is True

    assert (await main.fetch_sandbox_health(""))["configured"] is False
