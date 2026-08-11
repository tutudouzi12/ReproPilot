from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


TaskStatus = Literal[
    "pending",
    "ready",
    "in_progress",
    "completed",
    "failed",
    "blocked",
    "skipped",
    "canceled",
    "awaiting_approval",
]


class TaskContract(BaseModel):
    version: str = "1.0"
    input_artifacts: list[str] = Field(default_factory=list)
    output_artifacts: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)


class TaskNode(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    name: str
    type: str
    description: str
    assigned_to: str
    status: TaskStatus = "pending"
    dependencies: list[str] = Field(default_factory=list)
    required_artifacts: list[str] = Field(default_factory=list)
    output_artifacts: list[str] = Field(default_factory=list)
    parallelizable: bool = True
    priority: int = 0
    retry_limit: int = 1
    run_count: int = 0
    execution_id: str | None = None
    execution_epoch: int = 0
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    timeout_seconds: int = 120
    contract: TaskContract = Field(default_factory=TaskContract)
    inputs: dict[str, Any] = Field(default_factory=dict)
    result: str | None = None
    code: str | None = None
    structured_data: str | None = None
    image_base64: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class GraphEdge(BaseModel):
    id: str
    from_: str = Field(alias="from", serialization_alias="from")
    to: str
    type: str = "dependency"

    model_config = {"populate_by_name": True}


class ApprovalState(BaseModel):
    required: bool = False
    status: str = "not_required"
    reason: str | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None


class RunBudget(BaseModel):
    max_task_attempts: int = 20
    max_duration_seconds: int = 900


class RunUsage(BaseModel):
    task_attempts: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None


class GraphMeta(BaseModel):
    total_nodes: int = 0
    completed_nodes: int = 0
    failed_nodes: int = 0
    blocked_nodes: int = 0
    in_progress_nodes: int = 0
    ready_nodes: int = 0


class PlanGraph(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    user_intent: str
    intent_type: str
    status: TaskStatus = "pending"
    owner_id: str | None = None
    session_id: str | None = None
    trace_id: str = Field(default_factory=lambda: uuid4().hex)
    approval: ApprovalState = Field(default_factory=ApprovalState)
    budget: RunBudget = Field(default_factory=RunBudget)
    usage: RunUsage = Field(default_factory=RunUsage)
    nodes: list[TaskNode]
    edges: list[GraphEdge]
    artifacts: dict[str, Any] = Field(default_factory=dict)
    meta: GraphMeta = Field(default_factory=GraphMeta)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    def refresh_meta(self) -> None:
        self.meta = GraphMeta(
            total_nodes=len(self.nodes),
            completed_nodes=sum(n.status == "completed" for n in self.nodes),
            failed_nodes=sum(n.status == "failed" for n in self.nodes),
            blocked_nodes=sum(n.status == "blocked" for n in self.nodes),
            in_progress_nodes=sum(n.status == "in_progress" for n in self.nodes),
            ready_nodes=sum(n.status == "ready" for n in self.nodes),
        )
        self.updated_at = utc_now()


class PlanEvent(BaseModel):
    plan_id: str
    event_type: str
    task_id: str | None = None
    task_status: str | None = None
    trace_id: str | None = None
    span_id: str | None = None
    execution_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=utc_now)


class TaskExecutionResult(BaseModel):
    status: TaskStatus = "completed"
    result: str = ""
    code: str = ""
    structured_data: str = ""
    image_base64: str = ""
    error: str = ""
    logs: list[str] = Field(default_factory=list)
    artifact_values: dict[str, Any] = Field(default_factory=dict)


class IntentContext(BaseModel):
    raw_intent: str
    rewritten_intent: str = ""
    intent_type: str
    entities: dict[str, Any] = Field(default_factory=dict)
    constraints: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.0
    reasoning: str = ""
    source: str = "rule_fallback"


class PlanRequest(BaseModel):
    intent: str = Field(min_length=1)
    attachments: list[str] = Field(default_factory=list, max_length=8)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)


class ExecuteTaskRequest(BaseModel):
    task_id: str
    task_name: str
    task_type: str = "chat"
    task_description: str
    assigned_to: str
    inputs: dict[str, Any] = Field(default_factory=dict)


class ReassignTaskRequest(BaseModel):
    assigned_to: str = Field(min_length=1)
