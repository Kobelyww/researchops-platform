import type { RunMetrics } from "@/lib/types";

function formatNumber(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toLocaleString("en-US")
    : "—";
}

function formatUsd(value: unknown): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  if (value === 0) return "$0.00";
  return `$${value >= 1 ? value.toFixed(2) : value.toFixed(4)}`;
}

function formatSeconds(value: unknown): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return `${Math.round(value * 10) / 10}s`;
}

export function MetricsPanel({ metrics }: { metrics?: RunMetrics | null }) {
  const failedCalls =
    typeof metrics?.failed_calls === "number" && Number.isFinite(metrics.failed_calls)
      ? metrics.failed_calls
      : 0;
  const retries =
    typeof metrics?.retries === "number" && Number.isFinite(metrics.retries) ? metrics.retries : 0;

  const cells: { label: string; value: string; tone?: string }[] = [
    { label: "Tool calls", value: formatNumber(metrics?.tool_calls) },
    {
      label: "Failed calls",
      value: formatNumber(metrics?.failed_calls),
      tone: failedCalls > 0 ? "text-red-300" : undefined,
    },
    {
      label: "Retries",
      value: formatNumber(metrics?.retries),
      tone: retries > 0 ? "text-amber-300" : undefined,
    },
    { label: "Input tokens", value: formatNumber(metrics?.input_tokens), tone: "text-cyan-300" },
    { label: "Output tokens", value: formatNumber(metrics?.output_tokens), tone: "text-cyan-300" },
    { label: "Cost (USD)", value: formatUsd(metrics?.cost_usd), tone: "text-emerald-300" },
    { label: "Latency", value: formatSeconds(metrics?.latency_s), tone: "text-emerald-300" },
  ];

  return (
    <section className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="font-mono text-[11px] uppercase tracking-wider text-zinc-500">
          Observability
        </h2>
        {!metrics && <span className="font-mono text-[11px] text-zinc-600">no metrics yet</span>}
      </div>
      <div className="grid grid-cols-2 gap-2">
        {cells.map((cell) => (
          <div key={cell.label} className="rounded-lg border border-white/5 bg-black/30 px-3 py-2.5">
            <p className="font-mono text-[10px] uppercase tracking-wider text-zinc-500">
              {cell.label}
            </p>
            <p className={`mt-1 font-mono text-lg font-semibold ${cell.tone ?? "text-zinc-100"}`}>
              {cell.value}
            </p>
          </div>
        ))}
      </div>
    </section>
  );
}
