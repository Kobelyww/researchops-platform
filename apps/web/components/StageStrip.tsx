import { Fragment } from "react";

import type { AgentStatus, PlanTask } from "@/lib/types";

import { StageStatusIcon, type StageState } from "./StatusBadge";

interface StageDef {
  key: string;
  label: string;
  hint: string;
  /** PlanTask kinds that belong to this stage */
  kinds: string[];
  /** Agent name fragments that belong to this stage */
  agentNames: string[];
}

const STAGES: StageDef[] = [
  { key: "planner", label: "Planner", hint: "Decompose the goal", kinds: [], agentNames: ["planner"] },
  { key: "research", label: "Research", hint: "Papers & prior art", kinds: ["research"], agentNames: ["researcher"] },
  { key: "code", label: "Code", hint: "Repos & implementation", kinds: ["repository", "code"], agentNames: ["repository", "coder"] },
  { key: "experiment", label: "Experiment", hint: "Execute & measure", kinds: ["experiment"], agentNames: ["experimenter"] },
  { key: "review", label: "Review", hint: "Critique & validate", kinds: [], agentNames: ["reviewer"] },
  { key: "report", label: "Report", hint: "Write it up", kinds: ["report"], agentNames: [] },
];

const STATE_LABEL: Record<StageState, string> = {
  pending: "pending",
  running: "running",
  done: "done",
  failed: "failed",
};

const STATE_TEXT: Record<StageState, string> = {
  pending: "text-zinc-500",
  running: "text-amber-300",
  done: "text-emerald-300",
  failed: "text-red-300",
};

const STATE_CARD: Record<StageState, string> = {
  pending: "border-white/10 bg-white/[0.03]",
  running: "border-amber-500/40 bg-amber-500/[0.06]",
  done: "border-emerald-500/30 bg-emerald-500/[0.04]",
  failed: "border-red-500/40 bg-red-500/[0.06]",
};

function norm(value: string | undefined): string {
  return (value ?? "").trim().toLowerCase();
}

function isDoneStatus(status: string): boolean {
  return ["done", "completed", "complete", "success", "succeeded", "finished"].includes(status);
}

function isRunningStatus(status: string): boolean {
  return ["running", "in_progress", "active", "working", "started"].includes(status);
}

function isFailedStatus(status: string): boolean {
  return ["failed", "error", "errored", "aborted"].includes(status);
}

function deriveStageState(
  stage: StageDef,
  plan: PlanTask[],
  agents: AgentStatus[],
  runStatus: string
): StageState {
  if (runStatus === "completed") return "done";

  const statuses: string[] = [];
  for (const task of plan) {
    if (stage.kinds.includes(norm(task.kind))) {
      statuses.push(norm(task.status));
    }
  }
  for (const agent of agents) {
    const name = norm(agent.name);
    if (stage.agentNames.some((candidate) => name.includes(candidate))) {
      statuses.push(norm(agent.status));
    }
  }

  if (statuses.length === 0) return "pending";
  if (statuses.some(isFailedStatus)) return "failed";
  if (statuses.some(isRunningStatus)) return "running";
  if (statuses.every(isDoneStatus)) return "done";
  if (statuses.some(isDoneStatus)) return "running";
  return "pending";
}

export function StageStrip({
  plan,
  agents,
  runStatus,
}: {
  plan: PlanTask[];
  agents: AgentStatus[];
  runStatus: string;
}) {
  return (
    <section>
      <div className="mb-2 flex items-baseline justify-between">
        <h2 className="font-mono text-[11px] uppercase tracking-wider text-zinc-500">Pipeline</h2>
        {plan.length === 0 && (
          <span className="font-mono text-[11px] text-zinc-600">waiting for the planner…</span>
        )}
      </div>
      <div className="flex flex-wrap items-stretch gap-2">
        {STAGES.map((stage, index) => {
          const state = deriveStageState(stage, plan, agents, runStatus);
          return (
            <Fragment key={stage.key}>
              <div
                className={`min-w-[140px] flex-1 rounded-xl border p-3.5 transition-colors ${STATE_CARD[state]}`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-[11px] uppercase tracking-wider text-zinc-300">
                    {stage.label}
                  </span>
                  <StageStatusIcon state={state} />
                </div>
                <p className="mt-1.5 text-xs text-zinc-500">{stage.hint}</p>
                <p className={`mt-2.5 font-mono text-[11px] ${STATE_TEXT[state]}`}>
                  {STATE_LABEL[state]}
                </p>
              </div>
              {index < STAGES.length - 1 && (
                <span className="hidden items-center self-center font-mono text-zinc-600 xl:flex">
                  →
                </span>
              )}
            </Fragment>
          );
        })}
      </div>
    </section>
  );
}
