import type { AgentStatus } from "@/lib/types";

const CANONICAL_AGENTS = ["Planner", "Researcher", "Repository", "Coder", "Experimenter", "Reviewer"];

interface AgentStyle {
  badge: string;
  dot: string;
  pulse?: boolean;
}

const AGENT_STATUS_STYLES: Record<string, AgentStyle> = {
  pending: { badge: "border-zinc-600/40 bg-zinc-500/10 text-zinc-400", dot: "bg-zinc-500" },
  idle: { badge: "border-zinc-600/40 bg-zinc-500/10 text-zinc-400", dot: "bg-zinc-500" },
  queued: { badge: "border-zinc-600/40 bg-zinc-500/10 text-zinc-400", dot: "bg-zinc-500" },
  running: { badge: "border-amber-500/40 bg-amber-500/10 text-amber-300", dot: "bg-amber-400", pulse: true },
  working: { badge: "border-amber-500/40 bg-amber-500/10 text-amber-300", dot: "bg-amber-400", pulse: true },
  waiting_approval: { badge: "border-violet-500/40 bg-violet-500/10 text-violet-300", dot: "bg-violet-400" },
  done: { badge: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300", dot: "bg-emerald-400" },
  completed: { badge: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300", dot: "bg-emerald-400" },
  succeeded: { badge: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300", dot: "bg-emerald-400" },
  failed: { badge: "border-red-500/40 bg-red-500/10 text-red-300", dot: "bg-red-400" },
  error: { badge: "border-red-500/40 bg-red-500/10 text-red-300", dot: "bg-red-400" },
};

const FALLBACK_STYLE: AgentStyle = {
  badge: "border-white/15 bg-white/5 text-zinc-300",
  dot: "bg-zinc-400",
};

function mergeAgents(agents: AgentStatus[]): AgentStatus[] {
  const byName = new Map<string, AgentStatus>();
  for (const agent of agents) {
    byName.set(agent.name.toLowerCase(), agent);
  }
  const merged: AgentStatus[] = CANONICAL_AGENTS.map(
    (name): AgentStatus =>
      byName.get(name.toLowerCase()) ?? { name, status: "pending", steps: 0, last_message: "" }
  );
  for (const agent of agents) {
    if (!CANONICAL_AGENTS.some((canonical) => canonical.toLowerCase() === agent.name.toLowerCase())) {
      merged.push(agent);
    }
  }
  return merged;
}

export function AgentGrid({ agents }: { agents?: AgentStatus[] }) {
  if (agents === undefined) {
    return (
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {Array.from({ length: 6 }).map((_, index) => (
          <div
            key={index}
            className="h-[104px] animate-pulse rounded-xl border border-white/10 bg-white/[0.03]"
          />
        ))}
      </div>
    );
  }

  const merged = mergeAgents(agents);

  return (
    <div>
      {agents.length === 0 && (
        <p className="mb-3 font-mono text-[11px] text-zinc-600">
          Agents will check in here once the run starts.
        </p>
      )}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {merged.map((agent, index) => {
          const style = AGENT_STATUS_STYLES[(agent.status ?? "").toLowerCase()] ?? FALLBACK_STYLE;
          const placeholder = !agent.last_message && agent.steps === 0;
          return (
            <div
              key={`${agent.name}-${index}`}
              className={`rounded-xl border border-white/10 bg-white/[0.03] p-4 ${
                placeholder ? "opacity-70" : ""
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="flex min-w-0 items-center gap-2 font-mono text-sm font-medium text-zinc-100">
                  <span
                    className={`h-1.5 w-1.5 shrink-0 rounded-full ${style.dot} ${
                      style.pulse ? "animate-pulse" : ""
                    }`}
                  />
                  <span className="truncate">{agent.name}</span>
                </span>
                <span
                  className={`shrink-0 rounded-full border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider ${style.badge}`}
                >
                  {agent.status || "unknown"}
                </span>
              </div>
              <p className="mt-1.5 font-mono text-[11px] text-zinc-600">
                {agent.steps} step{agent.steps === 1 ? "" : "s"}
              </p>
              <p className="mt-2 line-clamp-2 min-h-[2rem] text-xs leading-relaxed text-zinc-500">
                {agent.last_message || <span className="italic text-zinc-600">no activity yet</span>}
              </p>
            </div>
          );
        })}
      </div>
    </div>
  );
}
