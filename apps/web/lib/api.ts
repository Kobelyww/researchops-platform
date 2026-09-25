import type { Approval, RunDetail, TaskSummary } from "@/lib/types";

export const API_BASE: string =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export type ApprovalDecision = "approved" | "rejected" | "modified";

export interface CreateTaskResult {
  task_id: string;
  run_id: string;
}

function buildHeaders(extra?: HeadersInit): Headers {
  const headers = new Headers(extra);
  headers.set("Content-Type", "application/json");
  const apiKey = process.env.NEXT_PUBLIC_API_KEY;
  if (apiKey) {
    headers.set("X-API-Key", apiKey);
  }
  return headers;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: buildHeaders(init?.headers),
      cache: "no-store",
    });
  } catch {
    throw new Error(`Cannot reach the ResearchOps API at ${API_BASE}`);
  }

  if (!response.ok) {
    let detail = response.statusText || "request failed";
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (body && typeof body.detail === "string") {
        detail = body.detail;
      }
    } catch {
      // non-JSON error body — keep the status text
    }
    throw new Error(`API error ${response.status}: ${detail}`);
  }

  return (await response.json()) as T;
}

export async function createTask(
  goal: string,
  requirements: string[]
): Promise<CreateTaskResult> {
  return request<CreateTaskResult>("/api/tasks", {
    method: "POST",
    body: JSON.stringify({
      goal,
      requirements: requirements.map((item) => item.trim()).filter(Boolean),
    }),
  });
}

export async function listTasks(): Promise<TaskSummary[]> {
  const data = await request<TaskSummary[] | { tasks?: TaskSummary[] }>("/api/tasks");
  if (Array.isArray(data)) return data;
  return data.tasks ?? [];
}

export function getRun(runId: string): Promise<RunDetail> {
  return request<RunDetail>(`/api/runs/${encodeURIComponent(runId)}`);
}

export function decideApproval(
  approvalId: string,
  decision: ApprovalDecision,
  note?: string
): Promise<Approval> {
  return request<Approval>(`/api/approvals/${encodeURIComponent(approvalId)}`, {
    method: "POST",
    body: JSON.stringify({ decision, note: note ?? null }),
  });
}
