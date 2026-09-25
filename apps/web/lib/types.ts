export type RunStatus =
  | "queued"
  | "running"
  | "awaiting_approval"
  | "completed"
  | "failed"
  | "rejected";

export type PlanTaskKind = "research" | "repository" | "code" | "experiment" | "report";

export interface PlanTask {
  id: string;
  kind: PlanTaskKind;
  title: string;
  status: string;
}

export interface AgentStatus {
  name: string;
  status: string;
  steps: number;
  last_message: string;
}

export type ApprovalRisk = "low" | "medium" | "high";

export type ApprovalState = "pending" | "approved" | "rejected" | "modified";

export interface Approval {
  id: string;
  action: string;
  /** JSON string describing the affected resources / parameters */
  detail: string;
  risk: ApprovalRisk;
  status: ApprovalState;
  estimated_cost_usd?: number;
  estimated_minutes?: number;
}

export interface RunMetrics {
  tool_calls: number;
  failed_calls: number;
  retries: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  latency_s: number;
}

export interface RunDetail {
  run_id: string;
  task_id: string;
  goal: string;
  status: RunStatus;
  plan: PlanTask[];
  agents: AgentStatus[];
  approvals: Approval[];
  metrics: RunMetrics;
  report_md: string | null;
  error?: string | null;
}

export type RunEventType = "step" | "tool" | "approval" | "status" | "metric";

export type RunEventLevel = "info" | "warn" | "error";

export interface RunEvent {
  ts: string | number;
  type: RunEventType;
  agent?: string;
  message?: string;
  level?: RunEventLevel;
  data?: unknown;
}

export interface TaskSummary {
  task_id: string;
  goal: string;
  status: RunStatus;
  created_at: string;
}
