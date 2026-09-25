"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { StatusBadge } from "@/components/StatusBadge";
import { listTasks } from "@/lib/api";
import type { TaskSummary } from "@/lib/types";

function formatCreated(value: string): string {
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) return value;
  return new Date(parsed).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export default function RunsPage() {
  const router = useRouter();
  const [tasks, setTasks] = useState<TaskSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await listTasks();
      setTasks(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load runs.");
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = setInterval(() => void load(), 5000);
    return () => clearInterval(timer);
  }, [load]);

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-white">Runs</h1>
          <p className="mt-1 font-mono text-xs text-zinc-500">
            All research tasks · auto-refreshing every 5s
          </p>
        </div>
        <Link
          href="/"
          className="rounded-lg border border-cyan-400/40 bg-cyan-400/10 px-3.5 py-2 font-mono text-xs text-cyan-200 transition-colors hover:bg-cyan-400/20"
        >
          + New run
        </Link>
      </div>

      {error && (
        <div
          className="mb-4 rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-3"
          role="alert"
        >
          <p className="text-sm font-medium text-red-200">Could not load runs</p>
          <p className="mt-1 font-mono text-xs text-red-300/90">{error}</p>
        </div>
      )}

      {tasks === null && !error ? (
        <div className="space-y-2 rounded-xl border border-white/10 bg-white/[0.03] p-4">
          {Array.from({ length: 5 }).map((_, index) => (
            <div key={index} className="h-10 animate-pulse rounded-lg bg-white/5" />
          ))}
        </div>
      ) : tasks !== null && tasks.length === 0 ? (
        <div className="rounded-xl border border-white/10 bg-white/[0.03] px-6 py-16 text-center">
          <p className="font-mono text-sm text-zinc-400">No runs yet.</p>
          <p className="mt-2 text-xs text-zinc-600">
            Launch your first mission from the{" "}
            <Link href="/" className="text-cyan-400 hover:underline">
              mission console
            </Link>
            .
          </p>
        </div>
      ) : tasks !== null ? (
        <div className="overflow-x-auto rounded-xl border border-white/10 bg-white/[0.03]">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-white/10 font-mono text-[11px] uppercase tracking-wider text-zinc-500">
                <th className="px-4 py-3 font-medium">Goal</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Created</th>
                <th className="px-4 py-3 text-right font-medium">Task</th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((task) => (
                <tr
                  key={task.task_id}
                  onClick={() => router.push(`/runs/${task.task_id}`)}
                  className="cursor-pointer border-b border-white/5 transition-colors last:border-b-0 hover:bg-white/[0.04]"
                >
                  <td className="max-w-md truncate px-4 py-3 text-zinc-200">{task.goal}</td>
                  <td className="px-4 py-3">
                    <StatusBadge status={task.status} pulse={task.status === "running"} />
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 font-mono text-xs text-zinc-500">
                    {formatCreated(task.created_at)}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-right font-mono text-xs text-zinc-600">
                    {task.task_id.slice(0, 8)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
