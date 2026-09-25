"use client";

import { useEffect, useRef, useState } from "react";

import { API_BASE, getRun } from "@/lib/api";
import type { RunDetail, RunEvent, RunStatus } from "@/lib/types";

const MAX_EVENTS = 500;

export interface UseRunStreamResult {
  run: RunDetail | null;
  events: RunEvent[];
  connected: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

function isRunDetail(value: unknown): value is RunDetail {
  if (typeof value !== "object" || value === null) return false;
  const record = value as Record<string, unknown>;
  return typeof record.run_id === "string";
}

function isRunEvent(value: unknown): value is RunEvent {
  if (typeof value !== "object" || value === null) return false;
  const record = value as Record<string, unknown>;
  return "ts" in record && "type" in record;
}

/**
 * Subscribes to the SSE stream for a run and keeps a merged RunDetail plus a
 * bounded event log. Falls back to polling getRun every 3s after the
 * EventSource errors twice (e.g. proxy without streaming support).
 */
export function useRunStream(runId: string): UseRunStreamResult {
  const [run, setRun] = useState<RunDetail | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const resyncTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!runId) return;

    let cancelled = false;
    let source: EventSource | null = null;
    let pollTimer: ReturnType<typeof setInterval> | null = null;
    let sourceErrors = 0;

    const fetchSnapshot = async () => {
      try {
        const detail = await getRun(runId);
        if (cancelled) return;
        setRun(detail);
        setError(null);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load run");
        }
      }
    };

    const startPolling = () => {
      if (pollTimer !== null || cancelled) return;
      void fetchSnapshot();
      pollTimer = setInterval(() => void fetchSnapshot(), 3000);
    };

    const scheduleResync = () => {
      if (resyncTimer.current) clearTimeout(resyncTimer.current);
      resyncTimer.current = setTimeout(() => void fetchSnapshot(), 300);
    };

    const pushEvent = (event: RunEvent) => {
      setEvents((prev) => {
        const next = [...prev, event];
        return next.length > MAX_EVENTS ? next.slice(next.length - MAX_EVENTS) : next;
      });
    };

    void fetchSnapshot();

    try {
      source = new EventSource(`${API_BASE}/api/runs/${encodeURIComponent(runId)}/events`);
      source.onopen = () => {
        sourceErrors = 0;
        if (!cancelled) setConnected(true);
      };
      source.onmessage = (message) => {
        let parsed: unknown;
        try {
          parsed = JSON.parse(message.data);
        } catch {
          return;
        }
        if (isRunDetail(parsed)) {
          setRun((prev) => (prev ? { ...prev, ...parsed } : parsed));
          if (!cancelled) setError(null);
          return;
        }
        if (isRunEvent(parsed)) {
          pushEvent(parsed);
          if (parsed.type === "status" || parsed.type === "approval" || parsed.type === "metric") {
            if (parsed.type === "status" && typeof parsed.data === "object" && parsed.data !== null) {
              const status = (parsed.data as Record<string, unknown>).status;
              if (typeof status === "string") {
                setRun((prev) => (prev ? { ...prev, status: status as RunStatus } : prev));
              }
            }
            scheduleResync();
          }
        }
      };
      source.onerror = () => {
        sourceErrors += 1;
        if (!cancelled) setConnected(false);
        if (sourceErrors >= 2) {
          source?.close();
          source = null;
          startPolling();
        }
      };
    } catch {
      startPolling();
    }

    return () => {
      cancelled = true;
      source?.close();
      if (pollTimer !== null) clearInterval(pollTimer);
      if (resyncTimer.current) clearTimeout(resyncTimer.current);
    };
  }, [runId]);

  const refresh = async () => {
    if (!runId) return;
    try {
      const detail = await getRun(runId);
      setRun(detail);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to refresh run");
    }
  };

  return { run, events, connected, error, refresh };
}
