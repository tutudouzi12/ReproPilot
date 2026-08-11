from __future__ import annotations

import json
import time

from fastapi.testclient import TestClient

import app.main as main
from app.agents import RoutedAgentExecutor
from app.events import EventBus
from app.scheduler import DAGScheduler
from app.store import FilePlanStore


def test_plan_executes_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setenv("OFFLINE_DEMO_MODE", "true")
    monkeypatch.setenv("REPOSITORY_OPERATIONS_ENABLED", "false")
    store = FilePlanStore(tmp_path / "plans.json")
    events = EventBus(store)
    executor = RoutedAgentExecutor()
    scheduler = DAGScheduler(store, events, executor, max_concurrent=2)
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "events", events)
    monkeypatch.setattr(main, "scheduler", scheduler)
    monkeypatch.setattr(main, "agents", executor)
    monkeypatch.setattr(main, "UPLOAD_ROOT", tmp_path / "uploads")

    with TestClient(main.app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["backend"]["runtime"] == "python"

        created = client.post(
            "/api/plan",
            json={"intent": "用 Python 做一个轻量论文复现实验"},
            headers={"X-User-Id": "test-user", "X-Session-Id": "test-session"},
        )
        assert created.status_code == 200
        graph = created.json()["plan_graph"]
        assert graph["owner_id"] == "test-user"
        assert [node["type"] for node in graph["nodes"]] == [
            "paper_parse",
            "claim_rubric_extract",
            "repo_discovery",
            "repo_prepare",
            "resolve_dependencies",
            "prepare_runtime",
            "install_dependencies",
            "paper_code_execute",
            "paper_compare",
            "claim_evidence_build",
        ]

        plan_id = graph["id"]
        started = client.post(f"/api/plans/{plan_id}/execute")
        assert started.status_code == 202

        for _ in range(100):
            current = client.get(f"/api/plans/{plan_id}").json()["plan_graph"]
            if current["status"] in {"completed", "failed"}:
                break
            time.sleep(0.02)

        assert current["status"] == "completed"
        assert all(node["status"] == "completed" for node in current["nodes"])
        assert any("OFFLINE_DEMO_UNVERIFIED" in (node.get("code") or "") for node in current["nodes"])
        assert current["artifacts"]["claim_rubric"]["value"]
        assert current["artifacts"]["claim_rubric"]["type"] == "json"
        assert current["artifacts"]["claim_rubric"]["producer_task_id"]
        evidence_graph = current["artifacts"]["claim_evidence_graph"]["value"]
        assert '"version":"claim.evidence/v1"' in evidence_graph
        evidence_payload = json.loads(evidence_graph)
        assert evidence_payload["summary"]["unverifiable"] == 1
        assert evidence_payload["summary"]["partially_reproduced"] == 0

        history = client.get(f"/api/plans/{plan_id}/events").json()["events"]
        event_types = [event["event_type"] for event in history]
        assert event_types[0] == "plan_started"
        assert event_types[-1] == "plan_completed"
        assert event_types.count("task_completed") == len(graph["nodes"])
        assert event_types.count("artifact_created") == len(graph["nodes"])
        assert "task_ready" in event_types
        assert "task_log" in event_types
        artifact_event = next(event for event in history if event["event_type"] == "artifact_created")
        assert artifact_event["payload"]["artifact_keys"]
        completed_event = next(event for event in history if event["event_type"] == "task_completed")
        assert "result" in completed_event["payload"]

        # A client that reconnects after completion receives persisted history
        # and the terminal event instead of waiting forever for a live event.
        replay = client.get(f"/api/plans/{plan_id}/stream")
        assert replay.status_code == 200
        assert "event: plan_event" in replay.text
        assert '"event_type": "plan_completed"' in replay.text


def test_unknown_plan_routes_return_not_found(tmp_path, monkeypatch):
    store = FilePlanStore(tmp_path / "plans.json")
    events = EventBus(store)
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "events", events)
    monkeypatch.setattr(main, "scheduler", DAGScheduler(store, events, RoutedAgentExecutor()))
    monkeypatch.setattr(main, "UPLOAD_ROOT", tmp_path / "uploads")

    with TestClient(main.app) as client:
        assert client.get("/api/plans/missing").status_code == 404
        assert client.get("/api/plans/missing/events").status_code == 404
        assert client.post("/api/plans/missing/execute").status_code == 404
        assert client.get("/api/plans/missing/stream").status_code == 404


def test_strict_api_plan_fails_instead_of_faking_missing_dependencies(tmp_path, monkeypatch):
    monkeypatch.setenv("OFFLINE_DEMO_MODE", "false")
    monkeypatch.setenv("REPOSITORY_OPERATIONS_ENABLED", "false")
    store = FilePlanStore(tmp_path / "plans.json")
    events = EventBus(store)
    executor = RoutedAgentExecutor()
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "events", events)
    monkeypatch.setattr(main, "scheduler", DAGScheduler(store, events, executor))
    monkeypatch.setattr(main, "agents", executor)
    monkeypatch.setattr(main, "UPLOAD_ROOT", tmp_path / "uploads")

    with TestClient(main.app) as client:
        created = client.post(
            "/api/plan",
            json={"intent": "用 Python 做一个轻量论文复现实验"},
            headers={"X-User-Id": "strict-user"},
        ).json()["plan_graph"]
        client.post(f"/api/plans/{created['id']}/execute", headers={"X-User-Id": "strict-user"})
        for _ in range(100):
            current = client.get(f"/api/plans/{created['id']}", headers={"X-User-Id": "strict-user"}).json()["plan_graph"]
            if current["status"] in {"completed", "failed"}:
                break
            time.sleep(0.02)
        history = client.get(
            f"/api/plans/{created['id']}/events",
            headers={"X-User-Id": "strict-user"},
        ).json()["events"]

    assert current["status"] == "failed"
    discovery = next(node for node in current["nodes"] if node["type"] == "repo_discovery")
    assert discovery["status"] == "failed"
    assert "trusted repository candidate" in discovery["error"]
    terminal = next(event for event in history if event["event_type"] == "plan_failed")
    failed_errors = {node["error"] for node in current["nodes"] if node["status"] == "failed"}
    assert terminal["payload"]["error"] in failed_errors


def test_chat_and_direct_execution_work_without_api_key(tmp_path, monkeypatch):
    monkeypatch.setenv("OFFLINE_DEMO_MODE", "true")
    store = FilePlanStore(tmp_path / "plans.json")
    events = EventBus(store)
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "events", events)
    executor = RoutedAgentExecutor()
    monkeypatch.setattr(main, "scheduler", DAGScheduler(store, events, executor))
    monkeypatch.setattr(main, "agents", executor)
    monkeypatch.setattr(main, "UPLOAD_ROOT", tmp_path / "uploads")

    with TestClient(main.app) as client:
        chat = client.post("/api/chat", json={"message": "解释 DAG 调度"})
        assert chat.status_code == 200
        assert "离线演示模式" in chat.json()["response"]

        with client.stream(
            "POST",
            "/api/execute",
            json={
                "task_id": "direct-1",
                "task_name": "生成代码",
                "task_type": "coding",
                "task_description": "生成一个均值计算实验",
                "assigned_to": "coder_agent",
                "inputs": {},
            },
        ) as response:
            body = "".join(response.iter_text())
        assert response.status_code == 200
        assert "event: result" in body
        assert "OFFLINE_DEMO_UNVERIFIED" in body


def test_direct_execution_stream_emits_error_in_strict_mode(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OFFLINE_DEMO_MODE", "false")
    store = FilePlanStore(tmp_path / "plans.json")
    events = EventBus(store)
    executor = RoutedAgentExecutor()
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "events", events)
    monkeypatch.setattr(main, "scheduler", DAGScheduler(store, events, executor))
    monkeypatch.setattr(main, "agents", executor)
    monkeypatch.setattr(main, "UPLOAD_ROOT", tmp_path / "uploads")

    with TestClient(main.app) as client:
        response = client.post(
            "/api/execute",
            json={
                "task_id": "strict-direct",
                "task_name": "generate",
                "task_type": "generate_code",
                "task_description": "generate Python",
                "assigned_to": "coder_agent",
            },
        )

    assert response.status_code == 200
    assert "event: error" in response.text
    assert "OPENAI_API_KEY" in response.text
    assert "event: result" not in response.text


def test_chat_returns_actionable_error_in_strict_mode(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OFFLINE_DEMO_MODE", "false")
    store = FilePlanStore(tmp_path / "plans.json")
    events = EventBus(store)
    executor = RoutedAgentExecutor()
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "events", events)
    monkeypatch.setattr(main, "scheduler", DAGScheduler(store, events, executor))
    monkeypatch.setattr(main, "agents", executor)

    with TestClient(main.app) as client:
        response = client.post("/api/chat", json={"message": "翻译这段论文"})

    assert response.status_code == 503
    assert "OPENAI_API_KEY" in response.json()["detail"]


def test_upload_ownership_and_dataset_routing(tmp_path, monkeypatch):
    store = FilePlanStore(tmp_path / "plans.json")
    events = EventBus(store)
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "events", events)
    monkeypatch.setattr(main, "scheduler", DAGScheduler(store, events, RoutedAgentExecutor()))
    monkeypatch.setattr(main, "UPLOAD_ROOT", tmp_path / "uploads")

    with TestClient(main.app) as client:
        uploaded = client.post(
            "/api/uploads",
            files={"file": ("reviews.csv", b"review,label\ngood,positive\nbad,negative\n", "text/csv")},
            headers={"X-User-Id": "owner-a"},
        )
        assert uploaded.status_code == 200
        upload_id = uploaded.json()["id"]

        denied_content = client.get(
            f"/api/uploads/{upload_id}/content",
            headers={"X-User-Id": "owner-b"},
        )
        assert denied_content.status_code == 403

        denied_plan = client.post(
            "/api/plan",
            json={"intent": "用数据跑 benchmark", "attachments": [upload_id]},
            headers={"X-User-Id": "owner-b", "X-Session-Id": "session-b"},
        )
        assert denied_plan.status_code == 403

        created = client.post(
            "/api/plan",
            json={"intent": "用自有数据跑 benchmark，输入列是 review，标签列是 label", "attachments": [upload_id]},
            headers={"X-User-Id": "owner-a", "X-Session-Id": "session-a"},
        )
        assert created.status_code == 200
        graph = created.json()["plan_graph"]
        assert graph["intent_type"] == "Custom_Benchmark"
        assert len(graph["nodes"]) == 11
        assert graph["nodes"][0]["inputs"]["uploaded_files"][0]["sha256"] == uploaded.json()["sha256"]
        assert "storage_path" not in created.text
        assert "text_excerpt" not in created.text

        internal_upload = main.uploads.resolve_owned([upload_id], "owner-a")[0]
        assert internal_upload["storage_path"]
        assert "review,label" in internal_upload["text_excerpt"]


def test_full_reproduction_requires_owner_approval(tmp_path, monkeypatch):
    store = FilePlanStore(tmp_path / "plans.json")
    events = EventBus(store)
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "events", events)
    monkeypatch.setattr(main, "scheduler", DAGScheduler(store, events, RoutedAgentExecutor()))
    monkeypatch.setattr(main, "UPLOAD_ROOT", tmp_path / "uploads")

    with TestClient(main.app) as client:
        created = client.post(
            "/api/plan",
            json={"intent": "完整复现 Attention Is All You Need，运行 WMT14 BLEU"},
            headers={"X-User-Id": "owner", "X-Session-Id": "session"},
        )
        assert created.status_code == 200
        body = created.json()
        assert body["plan_graph"]["status"] == "awaiting_approval"
        assert body["clarification"]["required"] is True
        plan_id = body["plan_graph"]["id"]

        denied = client.post(f"/api/plans/{plan_id}/execute", headers={"X-User-Id": "owner"})
        assert denied.status_code == 409
        foreign = client.post(f"/api/plans/{plan_id}/approve", headers={"X-User-Id": "other"})
        assert foreign.status_code == 403
        approved = client.post(f"/api/plans/{plan_id}/approve", headers={"X-User-Id": "owner"})
        assert approved.status_code == 200
        current = client.get(f"/api/plans/{plan_id}", headers={"X-User-Id": "owner"}).json()["plan_graph"]
        assert current["status"] == "pending"
        assert current["approval"]["approved_by"] == "owner"
        assert current["approval"]["approved_at"]
