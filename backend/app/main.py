from __future__ import annotations

import asyncio
import hmac
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import httpx
from fastapi import FastAPI, File, Header, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse

from .agents import RoutedAgentExecutor
from .events import EventBus
from .models import ChatRequest, ExecuteTaskRequest, PlanEvent, PlanRequest, ReassignTaskRequest, TaskNode, utc_now
from .autoresearch import parse_uploaded_research_spec
from .planner import Planner
from .scheduler import DAGScheduler, SchedulerConflict
from .safe_http import open_pinned_pdf, resolve_public_addresses, validate_pdf_url
from .store import FilePlanStore, PlanNotFound
from .uploads import UploadRegistry, validate_upload


DATA_PATH = Path(os.getenv("PLAN_STORE_PATH", "./data/plans.json"))
UPLOAD_ROOT = Path(os.getenv("UPLOAD_ROOT", "./data/uploads"))
uploads = UploadRegistry(UPLOAD_ROOT)
store = FilePlanStore(DATA_PATH)
events = EventBus(store)
agents = RoutedAgentExecutor()
planner = Planner()
scheduler = DAGScheduler(store, events, agents, int(os.getenv("MAX_CONCURRENT_TASKS", "2")))


@asynccontextmanager
async def lifespan(_: FastAPI):
    await store.load()
    uploads.root = UPLOAD_ROOT
    uploads.index_path = UPLOAD_ROOT / "uploads.json"
    uploads.load()
    yield


app = FastAPI(title="ReproPilot Python API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173").split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def api_auth(request: Request, call_next):
    expected = os.getenv("API_AUTH_TOKEN", "").strip()
    if expected and request.url.path.startswith("/api/") and request.url.path != "/api/health":
        provided = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if not hmac.compare_digest(provided, expected):
            return Response(
                content=json.dumps({"error": "invalid API bearer token"}),
                status_code=401,
                media_type="application/json",
            )
    return await call_next(request)


def identity(value: str | None, prefix: str, request: Request | None = None) -> str:
    if value and value.strip():
        return value.strip()
    if request is not None:
        cookie_name = "repropilot_anon_user_id" if prefix == "anon" else "repropilot_session_id"
        cookie = request.cookies.get(cookie_name, "").strip()
        if cookie:
            return cookie
    return f"{prefix}-{uuid4().hex}"


async def plan_or_404(plan_id: str):
    try:
        return await store.get_plan(plan_id)
    except PlanNotFound as exc:
        raise HTTPException(status_code=404, detail="plan not found") from exc


async def authorized_plan(plan_id: str, request: Request, x_user_id: str | None):
    plan = await plan_or_404(plan_id)
    user_id = identity(x_user_id, "anon", request)
    if plan.owner_id and plan.owner_id != user_id:
        raise HTTPException(status_code=403, detail="plan belongs to another user")
    return plan


def public_payload(value):
    """Remove server-local upload material from API-visible plan/context data."""
    if isinstance(value, list):
        return [public_payload(item) for item in value]
    if isinstance(value, dict):
        return {
            key: public_payload(item)
            for key, item in value.items()
            if key not in {"storage_path", "text_excerpt"}
        }
    return value


@app.get("/api/hello")
async def hello() -> dict[str, str]:
    return {"message": "ReproPilot Python backend"}


@app.get("/api/health")
async def health() -> dict:
    sandbox = await fetch_sandbox_health()
    return {
        "ok": bool(sandbox.get("ok") or sandbox.get("optional")),
        "backend": {"ok": True, "runtime": "python", "version": app.version},
        "sandbox": sandbox,
    }


async def fetch_sandbox_health(
    base_url: str | None = None,
    token: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict:
    configured_url = (base_url if base_url is not None else os.getenv("SANDBOX_URL", "")).rstrip("/")
    configured_token = (token if token is not None else os.getenv("SANDBOX_API_TOKEN", "")).strip()
    if not configured_url:
        return {"ok": False, "optional": True, "configured": False}
    headers = {"Authorization": f"Bearer {configured_token}"} if configured_token else {}
    try:
        async with httpx.AsyncClient(timeout=3, headers=headers, transport=transport) as client:
            response = await client.get(f"{configured_url}/api/v1/health")
            response.raise_for_status()
            status = response.json()
        return {"ok": bool(status.get("ok")), "optional": False, "configured": True, **status}
    except (httpx.HTTPError, ValueError) as exc:
        return {
            "ok": False,
            "optional": False,
            "configured": True,
            "error": str(exc)[:500],
        }


@app.post("/api/plan")
async def create_plan(
    payload: PlanRequest,
    request: Request,
    response: Response,
    x_user_id: str | None = Header(default=None),
    x_session_id: str | None = Header(default=None),
) -> dict:
    user_id = identity(x_user_id, "anon", request)
    session_id = identity(x_session_id, "session", request)
    context = planner.classify(payload.intent)
    try:
        resolved_uploads = uploads.resolve_owned(payload.attachments, user_id)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=f"upload not found: {exc.args[0]}") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=f"upload belongs to another user: {exc.args[0]}") from exc
    context.metadata["attachment_count"] = len(resolved_uploads)
    if resolved_uploads:
        context.entities["uploaded_files"] = resolved_uploads
        research_spec = parse_uploaded_research_spec(resolved_uploads)
        if research_spec is not None:
            context.intent_type = "AutoResearch"
            context.entities["needs_autoresearch"] = True
            context.entities["repository_revision"] = research_spec["repository_revision"]
        benchmark_file = any(item["name"].lower().endswith((".csv", ".tsv", ".json", ".jsonl")) for item in resolved_uploads)
        benchmark_intent = any(word in payload.intent.lower() for word in ("benchmark", "基准测试", "评测", "测评", "跑分"))
        if research_spec is None and benchmark_file and benchmark_intent:
            context.intent_type = "Custom_Benchmark"
            context.entities["needs_custom_benchmark"] = True
    plan = planner.build_plan(context)
    plan.owner_id = user_id
    plan.session_id = session_id
    plan.budget.max_task_attempts = int(os.getenv("PLAN_MAX_TASK_ATTEMPTS", str(plan.budget.max_task_attempts)))
    plan.budget.max_duration_seconds = int(os.getenv("PLAN_MAX_DURATION_SECONDS", str(plan.budget.max_duration_seconds)))
    requires_approval = os.getenv("REQUIRE_PLAN_APPROVAL", "false").lower() == "true" or context.constraints.get("reproduction_mode") == "full"
    plan.approval.required = requires_approval
    plan.approval.status = "pending" if requires_approval else "not_required"
    if requires_approval:
        plan.approval.reason = "high-risk or full reproduction plan"
        plan.status = "awaiting_approval"
    await store.save_plan(plan)
    response.set_cookie("repropilot_anon_user_id", user_id, httponly=True, samesite="lax")
    response.set_cookie("repropilot_session_id", session_id, httponly=True, samesite="lax")
    result = {
        "message": "Plan generated successfully",
        "plan_graph": public_payload(plan.model_dump(mode="json", by_alias=True)),
        "intent_context": public_payload(context.model_dump(mode="json")),
        "session_id": session_id,
        "anon_user_id": user_id,
        "user_id": user_id,
    }
    if context.intent_type == "Paper_Reproduction" and context.constraints.get("reproduction_mode") == "full":
        result["clarification"] = {
            "required": True,
            "type": "paper_reproduction_mode",
            "recommended_mode": "smoke",
            "question": "全量论文复现通常需要 CUDA GPU、大量磁盘和较长运行时间。是否先运行最小验证？",
            "options": [
                {"id": "smoke", "label": "运行最小验证", "description": "验证端到端链路，不执行全量训练。"},
                {"id": "full", "label": "开启全量复现", "description": "确认计算资源充足后执行。"},
            ],
            "resource_probe": {"cpu_count": os.cpu_count() or 1, "gpu_count": 0},
        }
    return result


@app.get("/api/plans/{plan_id}")
async def get_plan(plan_id: str, request: Request, x_user_id: str | None = Header(default=None)) -> dict:
    plan = await authorized_plan(plan_id, request, x_user_id)
    return {"plan_graph": public_payload(plan.model_dump(mode="json", by_alias=True))}


@app.get("/api/plans/{plan_id}/events")
async def get_plan_events(plan_id: str, request: Request, x_user_id: str | None = Header(default=None)) -> dict:
    await authorized_plan(plan_id, request, x_user_id)
    return {"events": [event.model_dump(mode="json") for event in await store.list_events(plan_id)]}


@app.post("/api/plans/{plan_id}/execute", status_code=202)
async def execute_plan(plan_id: str, request: Request, x_user_id: str | None = Header(default=None)) -> dict[str, str]:
    plan = await authorized_plan(plan_id, request, x_user_id)
    if plan.status not in {"pending", "ready"}:
        raise HTTPException(status_code=409, detail=f"plan cannot start from {plan.status}")
    try:
        scheduler.start(plan_id)
    except SchedulerConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"message": "Plan execution started", "plan_id": plan_id}


@app.post("/api/plans/{plan_id}/cancel")
async def cancel_plan(plan_id: str, request: Request, x_user_id: str | None = Header(default=None)) -> dict[str, str]:
    await authorized_plan(plan_id, request, x_user_id)
    try:
        await scheduler.cancel(plan_id)
    except SchedulerConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"message": "Plan canceled", "plan_id": plan_id}


@app.post("/api/plans/{plan_id}/approve")
async def approve_plan(plan_id: str, request: Request, x_user_id: str | None = Header(default=None)) -> dict[str, str]:
    plan = await authorized_plan(plan_id, request, x_user_id)
    if not plan.approval.required:
        raise HTTPException(status_code=409, detail="plan does not require approval")
    plan.approval.status = "approved"
    plan.approval.approved_by = identity(x_user_id, "anon", request)
    plan.approval.approved_at = utc_now()
    plan.status = "pending"
    await store.save_plan(plan)
    return {"message": "Plan approved", "plan_id": plan_id}


@app.post("/api/plans/{plan_id}/tasks/{task_id}/retry")
async def retry_task(plan_id: str, task_id: str, request: Request, x_user_id: str | None = Header(default=None)) -> dict[str, str]:
    await authorized_plan(plan_id, request, x_user_id)
    try:
        await scheduler.retry_task(plan_id, task_id)
    except (KeyError, SchedulerConflict) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"message": "Task reset for retry", "plan_id": plan_id, "task_id": task_id}


@app.post("/api/plans/{plan_id}/tasks/{task_id}/reassign")
async def reassign_task(plan_id: str, task_id: str, payload: ReassignTaskRequest, request: Request, x_user_id: str | None = Header(default=None)) -> dict[str, str]:
    await authorized_plan(plan_id, request, x_user_id)
    try:
        await scheduler.reassign_task(plan_id, task_id, payload.assigned_to)
    except (KeyError, SchedulerConflict) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "message": "Task reassigned",
        "plan_id": plan_id,
        "task_id": task_id,
        "assigned_to": payload.assigned_to,
    }


@app.get("/api/plans/{plan_id}/stream")
async def stream_plan_events(plan_id: str, request: Request, x_user_id: str | None = Header(default=None)) -> StreamingResponse:
    await authorized_plan(plan_id, request, x_user_id)
    queue = events.subscribe(plan_id)

    async def generate():
        sent: set[tuple[str, str, str | None, str | None]] = set()

        def event_key(event: PlanEvent) -> tuple[str, str, str | None, str | None]:
            return (event.timestamp.isoformat(), event.event_type, event.task_id, event.execution_id)

        def render(event: PlanEvent) -> str:
            data = json.dumps(event.model_dump(mode="json"), ensure_ascii=False)
            return f"event: plan_event\ndata: {data}\n\n"

        try:
            # Subscribe before reading history so events cannot fall into the
            # gap between replay and live delivery. Fingerprints suppress the
            # duplicates that can arise when an event lands in both places.
            history = await store.list_events(plan_id)
            for event in history:
                sent.add(event_key(event))
                yield render(event)
                if event.event_type in {"plan_completed", "plan_failed", "plan_canceled"}:
                    return
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                    key = event_key(event)
                    if key in sent:
                        continue
                    sent.add(key)
                    yield render(event)
                    if event.event_type in {"plan_completed", "plan_failed", "plan_canceled"}:
                        break
                except TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            events.unsubscribe(plan_id, queue)

    return StreamingResponse(generate(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})


@app.post("/api/chat")
async def chat(
    payload: ChatRequest,
    x_user_id: str | None = Header(default=None),
    x_session_id: str | None = Header(default=None),
) -> dict[str, str]:
    try:
        answer = await agents.chat(payload.message)
    except RuntimeError as exc:
        if "OPENAI_API_KEY" in str(exc):
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        raise
    return {
        "response": answer,
        "session_id": identity(x_session_id, "session"),
        "anon_user_id": identity(x_user_id, "anon"),
    }


@app.post("/api/execute")
async def execute_task(payload: ExecuteTaskRequest) -> StreamingResponse:
    task = TaskNode(
        id=payload.task_id,
        name=payload.task_name,
        type=payload.task_type,
        description=payload.task_description,
        assigned_to=payload.assigned_to,
        inputs=payload.inputs,
    )
    context = planner.classify(payload.task_description)
    plan = planner.build_plan(context)
    plan.nodes = [task]
    plan.edges = []

    async def generate():
        yield "event: log\ndata: Python Agent started\n\n"
        try:
            result = await agents.execute(task, plan)
            for line in result.logs:
                yield f"event: log\ndata: {line}\n\n"
            if result.status != "completed":
                yield f"event: error\ndata: {result.error or f'agent returned status {result.status}'}\n\n"
                return
            data = json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
            yield f"event: result\ndata: {data}\n\n"
        except Exception as exc:
            yield f"event: error\ndata: {str(exc)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/api/uploads")
async def upload_file(request: Request, response: Response, file: UploadFile = File(...), x_user_id: str | None = Header(default=None)) -> dict:
    max_bytes = int(os.getenv("UPLOAD_MAX_MB", "32")) * 1024 * 1024
    chunks: list[bytes] = []
    size = 0
    while chunk := await file.read(1024 * 1024):
        size += len(chunk)
        if size > max_bytes:
            raise HTTPException(status_code=413, detail="file too large")
        chunks.append(chunk)
    content = b"".join(chunks)
    try:
        validate_upload(file.filename or "upload.bin", file.content_type or "application/octet-stream", content)
    except ValueError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    user_id = identity(x_user_id, "anon", request)
    record = uploads.create(user_id, file.filename or "upload.bin", file.content_type or "application/octet-stream", content)
    response.set_cookie("repropilot_anon_user_id", user_id, httponly=True, samesite="lax")
    return record.public()


@app.get("/api/uploads/{upload_id}/content")
async def upload_content(upload_id: str, request: Request, x_user_id: str | None = Header(default=None)) -> Response:
    user_id = identity(x_user_id, "anon", request)
    try:
        record = uploads.get_owned(upload_id, user_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="upload not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="upload belongs to another user") from exc
    return Response(Path(record.storage_path).read_bytes(), media_type=record.content_type)


@app.get("/api/pdf-proxy")
async def pdf_proxy(url: str, request: Request) -> StreamingResponse:
    try:
        upstream = await open_pinned_pdf(url)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if 300 <= upstream.status_code < 400:
        location = upstream.headers.get("location", "")
        await upstream.close()
        raise HTTPException(status_code=502, detail=f"PDF redirects are not followed: {location[:120]}")
    if upstream.status_code >= 400:
        await upstream.close()
        raise HTTPException(status_code=upstream.status_code, detail="upstream PDF request failed")

    async def body():
        try:
            async for chunk in upstream.iter_bytes(int(os.getenv("PDF_PROXY_MAX_MB", "64")) * 1024 * 1024):
                if await request.is_disconnected():
                    break
                yield chunk
        finally:
            await upstream.close()

    return StreamingResponse(body(), media_type="application/pdf")


def validate_remote_pdf_url(url: str) -> None:
    try:
        host, port, _ = validate_pdf_url(url)
        resolve_public_addresses(host, port)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
