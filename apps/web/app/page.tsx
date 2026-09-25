"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import type { FormEvent } from "react";

import { createTask } from "@/lib/api";

interface Preset {
  label: string;
  goal: string;
  requirements: string[];
}

const PRESETS: Preset[] = [
  {
    label: "Reproduce a paper baseline",
    goal: "Reproduce the baseline of a cross-lingual speaker verification paper",
    requirements: [
      "Use the standard eval split and report EER / minDCF",
      "Compare reproduced numbers against the paper's reported baseline",
      "Note any dataset or training discrepancies",
    ],
  },
  {
    label: "Survey LLM agent benchmarks",
    goal: "Survey the latest LLM agent evaluation benchmarks and produce a comparison report",
    requirements: [
      "Cover benchmarks published within the last 12 months",
      "Compare task domains, metrics, and evaluation protocols",
      "Include a summary table and recommendations",
    ],
  },
  {
    label: "Analyze a GitHub repo",
    goal: "Clone and analyze a GitHub repo, run its test suite, and summarize architecture",
    requirements: [
      "Install dependencies in an isolated environment",
      "Run the full test suite and capture failures",
      "Summarize module structure and key entry points",
    ],
  },
];

export default function HomePage() {
  const router = useRouter();
  const [goal, setGoal] = useState("");
  const [requirements, setRequirements] = useState<string[]>([""]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const applyPreset = (preset: Preset) => {
    setGoal(preset.goal);
    setRequirements(preset.requirements.length > 0 ? [...preset.requirements] : [""]);
    setError(null);
  };

  const updateRequirement = (index: number, value: string) => {
    setRequirements((prev) => prev.map((item, i) => (i === index ? value : item)));
  };

  const addRequirement = () => {
    setRequirements((prev) => [...prev, ""]);
  };

  const removeRequirement = (index: number) => {
    setRequirements((prev) => prev.filter((_, i) => i !== index));
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmedGoal = goal.trim();
    if (!trimmedGoal) {
      setError("Describe your research goal before launching.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const result = await createTask(trimmedGoal, requirements);
      router.push(`/runs/${result.run_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unexpected error while creating the task.");
      setSubmitting(false);
    }
  };

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-8 py-6">
      <section className="text-center">
        <h1 className="text-5xl font-semibold tracking-tight text-white sm:text-6xl">
          Research<span className="text-cyan-400">Ops</span>
        </h1>
        <p className="mt-4 font-mono text-xs text-zinc-400 sm:text-sm">
          Autonomous Research <span className="text-cyan-400">→</span> Code{" "}
          <span className="text-cyan-400">→</span> Execute{" "}
          <span className="text-cyan-400">→</span> Evaluate{" "}
          <span className="text-cyan-400">→</span> Report
        </p>
      </section>

      <section>
        <h2 className="mb-2 text-center font-mono text-[11px] uppercase tracking-wider text-zinc-500">
          Preset missions
        </h2>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
          {PRESETS.map((preset) => (
            <button
              key={preset.label}
              type="button"
              onClick={() => applyPreset(preset)}
              className="rounded-xl border border-white/10 bg-white/[0.03] px-4 py-3 text-left transition-colors hover:border-cyan-400/40 hover:bg-cyan-400/[0.06]"
            >
              <span className="block font-mono text-xs font-medium text-zinc-200">
                {preset.label}
              </span>
              <span className="mt-1 block truncate text-[11px] text-zinc-500">{preset.goal}</span>
            </button>
          ))}
        </div>
      </section>

      <form onSubmit={handleSubmit} className="rounded-xl border border-white/10 bg-white/[0.03] p-6">
        <label
          htmlFor="goal"
          className="font-mono text-[11px] uppercase tracking-wider text-zinc-500"
        >
          Research goal
        </label>
        <textarea
          id="goal"
          value={goal}
          onChange={(event) => setGoal(event.target.value)}
          rows={4}
          placeholder="e.g. Reproduce the baseline of a cross-lingual speaker verification paper…"
          className="mt-2 w-full resize-none rounded-lg border border-white/10 bg-black/40 px-4 py-3 font-mono text-sm text-zinc-200 placeholder:text-zinc-600 focus:border-cyan-400/50 focus:outline-none focus:ring-1 focus:ring-cyan-400/30"
        />

        <div className="mt-6 flex items-center justify-between">
          <span className="font-mono text-[11px] uppercase tracking-wider text-zinc-500">
            Requirements
          </span>
          <button
            type="button"
            onClick={addRequirement}
            className="font-mono text-[11px] text-cyan-300/80 transition-colors hover:text-cyan-300"
          >
            + add
          </button>
        </div>
        <div className="mt-2 space-y-2">
          {requirements.map((requirement, index) => (
            <div key={index} className="flex items-center gap-2">
              <span className="w-8 shrink-0 text-right font-mono text-[11px] text-zinc-600">
                R{index + 1}
              </span>
              <input
                value={requirement}
                onChange={(event) => updateRequirement(index, event.target.value)}
                placeholder="Optional constraint or acceptance criterion"
                className="min-w-0 flex-1 rounded-lg border border-white/10 bg-black/40 px-3 py-2 font-mono text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-cyan-400/50 focus:outline-none focus:ring-1 focus:ring-cyan-400/30"
              />
              <button
                type="button"
                onClick={() => removeRequirement(index)}
                aria-label={`Remove requirement ${index + 1}`}
                className="shrink-0 rounded-lg border border-white/10 px-2.5 py-1.5 font-mono text-xs text-zinc-500 transition-colors hover:border-red-500/40 hover:text-red-300"
              >
                ×
              </button>
            </div>
          ))}
          {requirements.length === 0 && (
            <p className="px-1 py-1 font-mono text-[11px] text-zinc-600">
              No requirements — the agent will use sensible defaults.
            </p>
          )}
        </div>

        {error && (
          <div
            className="mt-6 rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-3"
            role="alert"
          >
            <p className="text-sm font-medium text-red-200">Could not launch the run</p>
            <p className="mt-1 font-mono text-xs text-red-300/90">{error}</p>
            <p className="mt-1 text-xs text-red-300/70">
              Check that the ResearchOps API is running and reachable, then try again.
            </p>
          </div>
        )}

        <div className="mt-6 flex items-center justify-end gap-3">
          <button
            type="submit"
            disabled={submitting}
            className="rounded-lg bg-cyan-500 px-5 py-2.5 font-mono text-sm font-medium text-zinc-950 transition-colors hover:bg-cyan-400 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {submitting ? "Launching…" : "Launch run"}
          </button>
        </div>
      </form>
    </div>
  );
}
