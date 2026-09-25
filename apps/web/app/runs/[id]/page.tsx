"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { AgentGrid } from "@/components/AgentGrid";
import { ApprovalPanel } from "@/components/ApprovalPanel";
import { EventFeed, eventTsToMs } from "@/components/EventFeed";
import { Markdown } from "@/components/Markdown";
import { MetricsPanel } from "@/components/MetricsPanel";
import { StageStrip } from "@/components/StageStrip";
import { StatusBadge } from "@/components/StatusBadge";
import { useRunStream } from "@/hooks/useRunStream";

const TERMINAL_STATUSES = ["completed", "failed", "rejected"];

function formatElapsed(ms: number): string {
  if (!Number.isFinite(ms) || ms <= 0) return "0s";
  const totalSeconds = Math.floor(ms / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) return `${hours}h ${minutes}m ${seconds}s`;
  if (minutes > 0) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
}

export default function RunDetailPage() {
  const params = useParams();
  const rawId = params?.id;
  const runId =
    typeof rawId === "string" ? rawId : Array.isArray(rawId) ? String(rawId[0] ?? "") : "";

  const { run, events, connected, error, refresh } = useRunStream(runId);

  const [now, setNow] = useState(() => Date.now());
  const startedAtRef = useRef<number | null>(null);

  const firstTs = events.length > 0 ? eventTsToMs(events[0].ts) : null;

  // Anchor the elapsed timer to the first event, or to first observation.
  useEffect(() => {
    if (startedAtRef.current !== null) return;
    if (firstTs !== null) {
      startedAtRef.current = firstTs;
    } else if (run) {
      startedAtRef.current = Date.now();
    }
  }, [firstTs, run]);

  const isActive = run !== null && !TERMINAL_STATUSES.includes(run.status);

  useEffect(() => {
    if (!isActive) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [isActive]);

  if (!runId) {
    return (
      <div className="rounded-xl border border-red-500/40 bg-red-500/10 p-6">
        <p className="text-sm font-medium text-red-200">Invalid run id</p>
        <p className="mt-1 text-xs text-red-300/80">
          The URL does not contain a run identifier.
        </p>
        <Link
          href="/runs"
          className="mt-4 inline-block rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 font-mono text-xs text-zinc-300 hover:bg-white/10"
        >
          ← All runs
        </Link>
      </div>
    );
  }

  if (!run) {
    return (
      <div className="space-y-4">
        <Link
          href="/runs"
          className="inline-flex items-center gap-1.5 font-mono text-xs text-zinc-500 transition-colors hover:text-cyan-300"
        >
          ← All runs
        </Link>
        {error ? (
          <div className="rounded-xl border border-red-500/40 bg-red-500/10 p-6">
            <p className="text-sm font-medium text-red-200">Could not load run</p>
            <p className="mt-1 font-mono text-xs text-red-300/90">{error}</p>
            <button
              type="button"
              onClick={() => void refresh()}
              className="mt-4 rounded-lg border border-red-500/40 bg-red-500/15 px-3 py-1.5 font-mono text-xs text-red-200 transition-colors hover:bg-red-500/25"
            >
              Retry
            </button>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="h-16 animate-pulse rounded-xl bg-white/5" />
            <div className="h-24 animate-pulse rounded-xl bg-white/5" />
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
              <div className="h-64 animate-pulse rounded-xl bg-white/5 lg:col-span-2" />
              <div className="h-64 animate-pulse rounded-xl bg-white/5" />
            </div>
            <p className="text-center font-mono text-xs text-zinc-600">Loading run {runId}…</p>
          </div>
        )}
      </div>
    );
  }

  const startedAt = startedAtRef.current;
  let elapsedLabel = "—";
  if (startedAt !== null) {
    if (isActive) {
      elapsedLabel = formatElapsed(now - startedAt);
    } else {
      const lastTs = events.length > 0 ? eventTsToMs(events[events.length - 1].ts) : null;
      if (lastTs !== null) {
        elapsedLabel = formatElapsed(lastTs - startedAt);
      } else if (typeof run.metrics?.latency_s === "number" && run.metrics.latency_s > 0) {
        elapsedLabel = `${run.metrics.latency_s}s`;
      }
    }
  }

  const approvals = run.approvals ?? [];
  const hasPendingApproval =
    run.status === "awaiting_approval" && approvals.some((item) => item.status === "pending");

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <Link
          href="/runs"
          className="mb-4 inline-flex items-center gap-1.5 font-mono text-xs text-zinc-500 transition-colors hover:text-cyan-300"
        >
          ← All runs
        </Link>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <h1 className="max-w-3xl text-xl font-semibold tracking-tight text-white sm:text-2xl">
            {run.goal || "Untitled run"}
          </h1>
          <StatusBadge status={run.status} pulse={isActive} />
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 font-mono text-[11px] text-zinc-500">
          <span>elapsed {elapsedLabel}</span>
          <span
            className={`inline-flex items-center gap-1.5 ${
              connected ? "text-emerald-300" : "text-amber-300"
            }`}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                connected ? "bg-emerald-400" : "animate-pulse bg-amber-400"
              }`}
            />
            {connected ? "stream live" : "polling"}
          </span>
          <span className="truncate text-zinc-600">run {run.run_id}</span>
          {run.task_id && <span className="truncate text-zinc-600">task {run.task_id}</span>}
        </div>
      </div>

      {/* Run-level error */}
      {run.error && (
        <div className="rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-3" role="alert">
          <p className="font-mono text-xs text-red-300">{run.error}</p>
        </div>
      )}

      {/* Sync warning (run loaded but streaming/polling is failing) */}
      {error && (
        <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-2.5 font-mono text-xs text-amber-300">
          sync warning: {error}
        </div>
      )}

      {/* Approval gate */}
      {hasPendingApproval && (
        <ApprovalPanel approvals={approvals} onDecided={() => void refresh()} />
      )}

      {/* Pipeline stages */}
      <StageStrip plan={run.plan ?? []} agents={run.agents ?? []} runStatus={run.status} />

      {/* Detail grid */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <section>
            <h2 className="mb-2 font-mono text-[11px] uppercase tracking-wider text-zinc-500">
              Agents
            </h2>
            <AgentGrid agents={run.agents} />
          </section>

          {run.report_md && (
            <section>
              <h2 className="mb-2 font-mono text-[11px] uppercase tracking-wider text-zinc-500">
                Report
              </h2>
              <div className="rounded-xl border border-white/10 bg-white/[0.03] p-6">
                <Markdown content={run.report_md} />
              </div>
            </section>
          )}
        </div>

        <div className="space-y-6">
          <MetricsPanel metrics={run.metrics ?? null} />
          <EventFeed events={events} connected={connected} />
        </div>
      </div>
    </div>
  );
}
