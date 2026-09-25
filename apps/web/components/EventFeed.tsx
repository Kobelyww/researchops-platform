"use client";

import { useEffect, useRef } from "react";

import type { RunEvent } from "@/lib/types";

const LEVEL_STYLES: Record<string, string> = {
  info: "text-zinc-400",
  warn: "text-amber-300",
  error: "text-red-300",
};

const TYPE_STYLES: Record<string, string> = {
  step: "text-cyan-300",
  tool: "text-violet-300",
  approval: "text-amber-300",
  status: "text-emerald-300",
  metric: "text-slate-400",
};

/** Accepts epoch seconds, epoch millis, or an ISO timestamp. */
export function eventTsToMs(ts: unknown): number | null {
  if (typeof ts === "number" && Number.isFinite(ts)) {
    return ts < 1e12 ? ts * 1000 : ts;
  }
  if (typeof ts === "string") {
    const parsed = Date.parse(ts);
    return Number.isNaN(parsed) ? null : parsed;
  }
  return null;
}

function formatClock(ts: unknown): string {
  const ms = eventTsToMs(ts);
  if (ms === null) return "--:--:--";
  return new Date(ms).toLocaleTimeString("en-US", { hour12: false });
}

export function EventFeed({
  events,
  connected,
}: {
  events: RunEvent[];
  connected?: boolean;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const pinnedRef = useRef(true);

  // Auto-scroll to the newest event, unless the user scrolled up to read.
  useEffect(() => {
    const el = containerRef.current;
    if (!el || !pinnedRef.current) return;
    el.scrollTop = el.scrollHeight;
  }, [events]);

  const handleScroll = () => {
    const el = containerRef.current;
    if (!el) return;
    pinnedRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
  };

  return (
    <section className="flex h-full flex-col rounded-xl border border-white/10 bg-white/[0.03]">
      <header className="flex items-center justify-between border-b border-white/10 px-4 py-3">
        <h2 className="font-mono text-[11px] uppercase tracking-wider text-zinc-500">Event feed</h2>
        <span className="font-mono text-[11px] text-zinc-600">
          {events.length} event{events.length === 1 ? "" : "s"}
          {connected === false ? " · polling" : ""}
        </span>
      </header>
      <div
        ref={containerRef}
        onScroll={handleScroll}
        className="h-96 flex-1 overflow-y-auto px-4 py-3 font-mono text-xs leading-relaxed"
      >
        {events.length === 0 ? (
          <p className="py-8 text-center text-zinc-600">
            No events yet. The stream will populate as the run progresses…
          </p>
        ) : (
          <ol className="space-y-1.5">
            {events.map((event, index) => {
              const level = (event.level ?? "info").toLowerCase();
              const type = (event.type ?? "").toLowerCase();
              const message =
                event.message ?? (event.data != null ? JSON.stringify(event.data) : "");
              return (
                <li key={index} className="flex gap-2">
                  <span className="shrink-0 text-zinc-600">{formatClock(event.ts)}</span>
                  <span className={`shrink-0 uppercase ${TYPE_STYLES[type] ?? "text-zinc-400"}`}>
                    [{event.type}]
                  </span>
                  {event.agent && <span className="shrink-0 text-cyan-400/90">{event.agent}</span>}
                  <span className={`min-w-0 break-words ${LEVEL_STYLES[level] ?? "text-zinc-400"}`}>
                    {message}
                  </span>
                </li>
              );
            })}
          </ol>
        )}
      </div>
    </section>
  );
}
