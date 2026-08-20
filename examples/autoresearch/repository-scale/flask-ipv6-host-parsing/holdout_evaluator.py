from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


sys.path.insert(0, str(Path.cwd() / "src"))

import flask.cli as flask_cli  # noqa: E402
import werkzeug.serving  # noqa: E402
from flask import Flask  # noqa: E402
from flask import session  # noqa: E402


def session_case(name: str, base_url: str) -> dict[str, Any]:
    app = Flask(f"session-{name}")
    app.secret_key = "repropilot-benchmark-secret"
    client = app.test_client()

    @app.get("/")
    def index() -> str:
        return str(session.get("value"))

    try:
        with client.session_transaction(base_url=base_url) as stored:
            stored["value"] = 42
        observed = client.get("/", base_url=base_url).text
        return {
            "name": name,
            "base_url": base_url,
            "expected": "42",
            "observed": observed,
            "passed": observed == "42",
        }
    except Exception as exc:
        return {
            "name": name,
            "base_url": base_url,
            "expected": "42",
            "observed": None,
            "error": f"{type(exc).__name__}: {exc}",
            "passed": False,
        }


def run_case(name: str, server_name: str, expected: tuple[str, int]) -> dict[str, Any]:
    app = Flask(f"run-{name}")
    app.config["SERVER_NAME"] = server_name
    captured: list[tuple[str, int]] = []
    original_run_simple = werkzeug.serving.run_simple
    original_banner = flask_cli.show_server_banner
    werkzeug.serving.run_simple = lambda host, port, *args, **kwargs: captured.append((host, port))
    flask_cli.show_server_banner = lambda *args, **kwargs: None
    try:
        app.run(load_dotenv=False)
        observed = captured[-1] if captured else None
        return {
            "name": name,
            "server_name": server_name,
            "expected": list(expected),
            "observed": list(observed) if observed else None,
            "passed": observed == expected,
        }
    except Exception as exc:
        return {
            "name": name,
            "server_name": server_name,
            "expected": list(expected),
            "observed": None,
            "error": f"{type(exc).__name__}: {exc}",
            "passed": False,
        }
    finally:
        werkzeug.serving.run_simple = original_run_simple
        flask_cli.show_server_banner = original_banner


results = [
    session_case("session_ipv4", "http://127.0.0.1:8000/"),
    session_case("session_ipv6_full", "http://[2001:db8::1]:8443/"),
    run_case("run_ipv4_port_zero", "127.0.0.1:0", ("127.0.0.1", 0)),
    run_case("run_ipv6_full", "[2001:db8::1]:8443", ("2001:db8::1", 8443)),
    run_case("run_ipv6_default_port", "[::1]", ("::1", 5000)),
]
passed = sum(result["passed"] for result in results)
print(
    json.dumps(
        {
            "metrics": {"ipv6_host_score": passed / len(results)},
            "passed": passed,
            "total": len(results),
            "cases": results,
        },
        ensure_ascii=False,
    )
)
