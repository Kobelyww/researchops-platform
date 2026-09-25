const RUN_STATUS_STYLES: Record<string, string> = {
  queued: "border-slate-500/40 bg-slate-500/10 text-slate-300",
  planning: "border-sky-500/40 bg-sky-500/10 text-sky-300",
  running: "border-amber-500/40 bg-amber-500/10 text-amber-300",
  awaiting_approval: "border-violet-500/40 bg-violet-500/10 text-violet-300",
  completed: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  failed: "border-red-500/40 bg-red-500/10 text-red-300",
  rejected: "border-rose-500/40 bg-rose-500/10 text-rose-300",
};

export function StatusBadge({
  status,
  pulse = false,
}: {
  status: string;
  pulse?: boolean;
}) {
  const style = RUN_STATUS_STYLES[status] ?? "border-white/15 bg-white/5 text-zinc-300";
  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-0.5 font-mono text-[11px] uppercase tracking-wider ${style}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full bg-current ${pulse ? "animate-pulse" : ""}`} />
      {status.replace(/_/g, " ")}
    </span>
  );
}

const RISK_STYLES: Record<string, string> = {
  low: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  medium: "border-amber-500/40 bg-amber-500/10 text-amber-300",
  high: "border-red-500/40 bg-red-500/10 text-red-300",
};

export function RiskBadge({ risk }: { risk: string }) {
  const style =
    RISK_STYLES[(risk ?? "").toLowerCase()] ?? "border-white/15 bg-white/5 text-zinc-300";
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider ${style}`}
    >
      risk: {(risk || "unknown").toLowerCase()}
    </span>
  );
}

export type StageState = "pending" | "running" | "done" | "failed";

export function StageStatusIcon({ state }: { state: StageState }) {
  if (state === "running") {
    return (
      <span className="relative flex h-2.5 w-2.5">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-400 opacity-60" />
        <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-amber-400" />
      </span>
    );
  }
  if (state === "done") {
    return (
      <svg viewBox="0 0 12 12" className="h-3 w-3 text-emerald-400" fill="none" aria-hidden>
        <circle cx="6" cy="6" r="5" stroke="currentColor" strokeWidth="1.2" />
        <path
          d="M3.8 6.2 5.3 7.7 8.3 4.4"
          stroke="currentColor"
          strokeWidth="1.2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    );
  }
  if (state === "failed") {
    return (
      <svg viewBox="0 0 12 12" className="h-3 w-3 text-red-400" fill="none" aria-hidden>
        <circle cx="6" cy="6" r="5" stroke="currentColor" strokeWidth="1.2" />
        <path
          d="M4.2 4.2 7.8 7.8 M7.8 4.2 4.2 7.8"
          stroke="currentColor"
          strokeWidth="1.2"
          strokeLinecap="round"
        />
      </svg>
    );
  }
  return <span className="h-2.5 w-2.5 rounded-full border border-zinc-600" />;
}
