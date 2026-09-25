"use client";

import { useState } from "react";

import { decideApproval } from "@/lib/api";
import type { Approval } from "@/lib/types";

import { RiskBadge } from "./StatusBadge";

type Decision = "approved" | "rejected" | "modified";

const DECISION_BUTTONS: { decision: Decision; label: string; className: string }[] = [
  {
    decision: "approved",
    label: "Approve",
    className: "border-emerald-500/50 bg-emerald-500/15 text-emerald-200 hover:bg-emerald-500/25",
  },
  {
    decision: "rejected",
    label: "Reject",
    className: "border-red-500/50 bg-red-500/15 text-red-200 hover:bg-red-500/25",
  },
  {
    decision: "modified",
    label: "Modify",
    className: "border-cyan-500/50 bg-cyan-500/15 text-cyan-200 hover:bg-cyan-500/25",
  },
];

function prettyDetail(detail: string): string {
  try {
    return JSON.stringify(JSON.parse(detail), null, 2);
  } catch {
    return detail;
  }
}

export function ApprovalPanel({
  approvals,
  onDecided,
}: {
  approvals: Approval[];
  onDecided: () => void;
}) {
  const pending = (approvals ?? []).filter((approval) => approval.status === "pending");

  if (pending.length === 0) return null;

  return (
    <section>
      <div className="mb-2 flex items-baseline justify-between">
        <h2 className="font-mono text-[11px] uppercase tracking-wider text-violet-300">
          Approval required
        </h2>
        <span className="font-mono text-[11px] text-zinc-600">
          {pending.length} pending
        </span>
      </div>
      <div className="space-y-3">
        {pending.map((approval) => (
          <ApprovalCard key={approval.id} approval={approval} onDecided={onDecided} />
        ))}
      </div>
    </section>
  );
}

function ApprovalCard({
  approval,
  onDecided,
}: {
  approval: Approval;
  onDecided: () => void;
}) {
  const [note, setNote] = useState("");
  const [busyDecision, setBusyDecision] = useState<Decision | null>(null);
  const [error, setError] = useState<string | null>(null);

  const decide = async (decision: Decision) => {
    setBusyDecision(decision);
    setError(null);
    try {
      await decideApproval(approval.id, decision, note.trim() ? note.trim() : undefined);
      onDecided();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit decision");
    } finally {
      setBusyDecision(null);
    }
  };

  return (
    <div className="rounded-xl border border-violet-500/40 bg-violet-500/[0.06] p-5 shadow-[0_0_40px_-12px_rgba(139,92,246,0.4)]">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-mono text-[11px] uppercase tracking-wider text-violet-300/80">action</p>
          <p className="mt-1 text-sm font-medium text-white">
            {approval.action || "Unnamed action"}
          </p>
        </div>
        <RiskBadge risk={approval.risk} />
      </div>

      <pre className="mt-4 max-h-48 overflow-auto rounded-lg border border-white/10 bg-black/50 p-3 font-mono text-[11px] leading-relaxed text-zinc-300">
        {prettyDetail(approval.detail ?? "")}
      </pre>

      {(approval.estimated_cost_usd != null || approval.estimated_minutes != null) && (
        <div className="mt-3 flex flex-wrap gap-2">
          {approval.estimated_cost_usd != null && (
            <span className="rounded-full border border-white/10 bg-white/5 px-2.5 py-1 font-mono text-[11px] text-zinc-300">
              est. cost ${approval.estimated_cost_usd.toFixed(2)}
            </span>
          )}
          {approval.estimated_minutes != null && (
            <span className="rounded-full border border-white/10 bg-white/5 px-2.5 py-1 font-mono text-[11px] text-zinc-300">
              est. {approval.estimated_minutes} min
            </span>
          )}
        </div>
      )}

      <textarea
        value={note}
        onChange={(event) => setNote(event.target.value)}
        rows={2}
        placeholder="Optional note attached to your decision…"
        className="mt-4 w-full resize-none rounded-lg border border-white/10 bg-black/40 px-3 py-2 font-mono text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-cyan-400/50 focus:outline-none focus:ring-1 focus:ring-cyan-400/30"
      />

      {error && (
        <p
          className="mt-3 rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 font-mono text-xs text-red-300"
          role="alert"
        >
          {error}
        </p>
      )}

      <div className="mt-4 flex flex-wrap gap-2">
        {DECISION_BUTTONS.map(({ decision, label, className }) => (
          <button
            key={decision}
            type="button"
            disabled={busyDecision !== null}
            onClick={() => void decide(decision)}
            className={`rounded-lg border px-4 py-2 font-mono text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${className}`}
          >
            {busyDecision === decision ? "Submitting…" : label}
          </button>
        ))}
      </div>
    </div>
  );
}
