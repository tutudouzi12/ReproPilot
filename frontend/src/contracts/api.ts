export type ChatAction =
  | 'open_pdf'
  | 'close_pdf'
  | 'view_plot'
  | 'view_report';

export interface ChatMessage {
  role: string;
  text: string;
  actions?: ChatAction[];
  taskId?: string;
  pdfUrl?: string;
}

export interface UploadedFile {
  id: string;
  name: string;
  content_type: string;
  size: number;
  sha256: string;
  content_url: string;
  created_at: string;
}

export interface Task {
  ID: string;
  Name: string;
  Type?: string;
  Description: string;
  AssignedTo: string;
  Status: string;
  Dependencies: string[];
  Inputs?: Record<string, unknown>;
  RequiredArtifacts?: string[];
  OutputArtifacts?: string[];
  Result?: string;
  Code?: string;
  StructuredData?: string;
  ImageBase64?: string;
}

export interface GraphTask {
  id: string;
  name: string;
  type: string;
  description: string;
  assigned_to: string;
  status: string;
  dependencies: string[];
  inputs?: Record<string, unknown>;
  required_artifacts: string[];
  output_artifacts: string[];
  parallelizable: boolean;
  priority: number;
  retry_limit: number;
  run_count: number;
  execution_id?: string;
  execution_epoch: number;
  lease_owner?: string;
  lease_expires_at?: string;
  timeout_seconds?: number;
  contract: {
    version: string;
    input_artifacts: string[];
    output_artifacts: string[];
    allowed_tools: string[];
  };
  result?: string;
  code?: string;
  structured_data?: string;
  image_base64?: string;
  image_base_64?: string;
  error?: string;
}

export interface GraphEdge {
  id: string;
  from: string;
  to: string;
  type: string;
}

export interface PlanGraph {
  id: string;
  user_intent: string;
  intent_type: string;
  status: string;
  owner_id?: string;
  session_id?: string;
  trace_id: string;
  approval: {
    required: boolean;
    status: string;
    reason?: string;
    approved_by?: string;
    approved_at?: string;
  };
  budget: {
    max_task_attempts: number;
    max_duration_seconds: number;
  };
  usage: {
    task_attempts: number;
    started_at?: string;
    finished_at?: string;
  };
  nodes: GraphTask[];
  edges: GraphEdge[];
  artifacts?: Record<string, unknown>;
}

export interface RunAssessment {
  version: 'autoresearch.assessment/v1';
  method: string;
  evidence: {
    trajectory_source: 'native_hash_linked' | 'derived_from_ledger';
    integrity: 'verified' | 'partial';
    source_bindings_verified?: boolean | null;
  };
  outcome: {
    status: 'passed' | 'failed' | 'not_assessable';
    metric_key?: string | null;
    baseline_score?: number | null;
    best_score?: number | null;
    directional_improvement?: number | null;
    validation_status: 'passed' | 'failed' | 'not_run';
    validation_mode?: string | null;
    validation_observed_score?: number | null;
    validation_passed_runs?: number | null;
    validation_failed_runs?: number | null;
  };
  compliance: {
    status: 'verified' | 'violated' | 'partial';
    hard_violation: boolean;
    hard_violation_reasons: string[];
    trajectory_chain_verified?: boolean | null;
    candidate_intact?: boolean | null;
    protected_files_intact?: boolean | null;
  };
  process: {
    status: 'complete' | 'partial';
    event_count?: number | null;
    completed_trials?: number | null;
    accepted_trials?: number | null;
    rollback_count?: number | null;
    stop_reason?: string | null;
  };
  scoring: {
    status: 'not_calculated';
    composite_score: null;
    reason: string;
  };
}

export interface AssessmentState {
  version: 'autoresearch.assessment-status/v1';
  status: 'available' | 'unavailable' | 'blocked';
  assessment: RunAssessment | null;
  reason?: string | null;
}

export interface IntentContext {
  raw_intent: string;
  intent_type: string;
  entities: Record<string, unknown>;
  constraints: Record<string, unknown>;
  metadata: Record<string, unknown>;
}

export interface PlanEvent {
  plan_id: string;
  event_type: string;
  task_id?: string;
  task_status?: string;
  payload?: Record<string, unknown>;
  timestamp: string;
  trace_id?: string;
  span_id?: string;
  execution_id?: string;
}

export interface NodeExecutionState {
  logs: string;
  result: string;
  code: string;
  structuredData: string;
  imageBase64?: string;
}

export interface ReproductionResourceProbe {
  cpu_count?: number;
  memory_gb?: number;
  disk_free_gb?: number;
  gpu_count?: number;
  gpu_names?: string[];
  thresholds?: Record<string, unknown>;
}

export interface ReproductionModeDecision {
  requested_mode?: string;
  effective_mode?: string;
  full_eligible?: boolean;
  reasons?: string[];
  probe?: ReproductionResourceProbe;
}

export interface PlanClarificationOption {
  id: string;
  label: string;
  description: string;
}

export interface PlanClarification {
  required?: boolean;
  type?: string;
  recommended_mode?: string;
  question: string;
  options?: PlanClarificationOption[];
  mode_decision?: ReproductionModeDecision;
  resource_probe?: ReproductionResourceProbe;
}

export interface PlanResponse {
  message: string;
  plan_graph: PlanGraph;
  clarification?: PlanClarification;
  intent_context?: IntentContext;
  session_id?: string;
  anon_user_id?: string;
  user_id?: string;
  assessment?: AssessmentState;
}

export interface ChatResponse {
  response: string;
  session_id?: string;
  anon_user_id?: string;
  user_id?: string;
}

export interface ExecutePlanResponse {
  message: string;
  plan_id: string;
}

export interface ExecuteTaskPayload {
  task_id: string;
  task_name: string;
  task_type?: string;
  task_description: string;
  assigned_to: string;
  inputs?: Record<string, unknown>;
}

export interface ExecuteTaskResultEvent {
  status?: string;
  result?: string;
  code?: string;
  structured_data?: string;
  image_base64?: string;
  image_base_64?: string;
  error?: string;
}
