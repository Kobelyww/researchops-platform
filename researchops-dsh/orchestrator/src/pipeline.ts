/**
 * ResearchOps pipeline core — the deterministic half of the orchestration,
 * ported from researchops-agent/src/researchops/graph/ (state, routing,
 * report). No I/O, no dsh imports: pure functions over plain data so the
 * routing decisions stay auditable and unit-testable.
 *
 * @module @researchops/dsh-orchestrator/pipeline
 */

/** One node of the planner's task graph (port of core.types.TaskNode). */
export interface TaskNode {
  id: string
  kind: 'research' | 'repository' | 'code' | 'experiment'
  title: string
  description: string
  dependsOn: string[]
  status: 'pending' | 'running' | 'done' | 'failed' | 'skipped'
}

/** One citation with its grounding verdict (port of core.types.Citation). */
export interface Citation {
  claim: string
  title: string
  url: string
  verified: boolean
}

/** One sandboxed experiment outcome (port of core.types.ExperimentResult). */
export interface ExperimentResult {
  name: string
  command: string
  status: 'success' | 'failed'
  metrics: Record<string, number>
  logExcerpt: string
}

export interface Plan {
  tasks: TaskNode[]
}

/** The pipeline's mutable state (port of graph/state.py, in-memory milestone). */
export interface PipelineState {
  goal: string
  plan: TaskNode[]
  findings: string[]
  citations: Citation[]
  experiments: ExperimentResult[]
  repairAttempts: number
  review: Review | undefined
}

export interface Review {
  approved: boolean
  confidence: number
  issues: string[]
}

/** First pending task whose dependencies are done (port of routing.next_ready_task). */
export function nextReadyTask(state: PipelineState): TaskNode | undefined {
  const done = new Set(state.plan.filter(t => t.status === 'done').map(t => t.id))
  return state.plan.find(t => t.status === 'pending' && t.dependsOn.every(d => done.has(d)))
}

/** Whether the plan contains an experiment task at all. */
export function hasExperimentTask(state: PipelineState): boolean {
  return state.plan.some(t => t.kind === 'experiment')
}

/**
 * Deterministic pre-review evaluation (port of nodes.evaluate's code half):
 * an experiment-bearing plan needs one successful experiment with metrics;
 * a research-only plan needs any stage output.
 */
export function evaluateSuccess(state: PipelineState): boolean {
  if (hasExperimentTask(state)) {
    return state.experiments.some(e => e.status === 'success' && Object.keys(e.metrics).length > 0)
  }
  return state.findings.length > 0
}

/** Citation grounding check (port of nodes._grounded_urls): a citation is
 * verified when its URL appeared in retrieved evidence text. */
export function groundCitations(state: PipelineState, evidence: string): Citation[] {
  return state.citations.map(c => ({ ...c, verified: evidence.includes(c.url) }))
}

/** Extract the first fenced/bare JSON object from an assistant reply
 * (port of agents.loop.extract_json_objects). */
export function extractJsonObject(text: string): Record<string, unknown> | undefined {
  const fenced = text.match(/```(?:json)?\s*(\{[\s\S]*?\})\s*```/)
  const candidates = fenced?.[1] !== undefined ? [fenced[1]] : []
  const bare = text.match(/\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}/)
  if (bare) candidates.push(bare[0])
  for (const candidate of candidates) {
    try {
      const parsed = JSON.parse(candidate) as unknown
      if (parsed !== null && typeof parsed === 'object' && !Array.isArray(parsed)) {
        return parsed as Record<string, unknown>
      }
    } catch {
      // try the next candidate
    }
  }
  return undefined
}

/** Parse the planner's task graph, falling back to a minimal sane plan
 * (port of agents.planner fallback). */
export function parsePlan(output: string): Plan {
  const obj = extractJsonObject(output)
  const raw = obj?.tasks
  if (Array.isArray(raw) && raw.length > 0) {
    const tasks: TaskNode[] = raw.slice(0, 8).map((t, i) => {
      const node = (t ?? {}) as Record<string, unknown>
      const kind = node.kind === 'repository' || node.kind === 'code' || node.kind === 'experiment'
        ? node.kind
        : 'research'
      const dependsOn = Array.isArray(node.depends_on)
        ? node.depends_on.filter((d): d is string => typeof d === 'string').slice(0, 8)
        : []
      return {
        id: String(node.id ?? `t${i + 1}`),
        kind,
        title: String(node.title ?? `task ${i + 1}`).slice(0, 200),
        description: String(node.description ?? '').slice(0, 1000),
        dependsOn,
        status: 'pending',
      }
    })
    return { tasks }
  }
  return {
    tasks: [
      { id: 't1', kind: 'research', title: 'Research the goal', description: '', dependsOn: [], status: 'pending' },
      { id: 't2', kind: 'experiment', title: 'Run a baseline check', description: '', dependsOn: ['t1'], status: 'pending' },
    ],
  }
}

/** Pull citations out of a researcher reply (port of loop._extract_citations). */
export function parseCitations(output: string): Citation[] {
  const obj = extractJsonObject(output)
  const raw = obj?.citations
  if (!Array.isArray(raw)) return []
  return raw.slice(0, 20)
    .filter((c): c is Record<string, unknown> => c !== null && typeof c === 'object' && typeof (c as Record<string, unknown>).url === 'string')
    .map(c => ({
      claim: String(c.claim ?? '').slice(0, 500),
      title: String(c.title ?? ''),
      url: String(c.url),
      verified: false,
    }))
}

/** Pull an experiment record out of an experimenter reply (port of nodes.experiment). */
export function parseExperiment(output: string): ExperimentResult {
  const obj = extractJsonObject(output) ?? {}
  const rawMetrics = (obj.metrics ?? {}) as Record<string, unknown>
  const metrics: Record<string, number> = {}
  for (const [k, v] of Object.entries(rawMetrics)) {
    if (typeof v === 'number') metrics[k] = v
  }
  const statusOk = String(obj.status ?? '').toLowerCase() === 'success'
  return {
    name: String(obj.experiment ?? 'experiment').slice(0, 120),
    command: String(obj.command ?? '').slice(0, 500),
    status: statusOk ? 'success' : 'failed',
    metrics,
    logExcerpt: String(obj.log_excerpt ?? '').slice(0, 2000),
  }
}

/** Pull the reviewer's verdict (port of agents.reviewer fallback). */
export function parseReview(output: string, fallback: Review): Review {
  const obj = extractJsonObject(output)
  if (obj === undefined || !('approved' in obj)) return fallback
  return {
    approved: Boolean(obj.approved),
    confidence: typeof obj.confidence === 'number' ? obj.confidence : 0.5,
    issues: Array.isArray(obj.issues) ? obj.issues.map(String).slice(0, 10) : [],
  }
}

/** Deterministic markdown report (port of graph/report.py, condensed). */
export function buildReport(state: PipelineState, evidence: string): string {
  const citations = groundCitations(state, evidence)
  const lines: string[] = []
  lines.push('# ResearchOps Report', '')
  lines.push(`**Goal:** ${state.goal}`, '')
  lines.push('## Plan & Execution', '', '| Task | Kind | Status |', '|------|------|--------|')
  for (const t of state.plan) lines.push(`| ${t.title} | ${t.kind} | ${t.status} |`)

  if (state.findings.length > 0) {
    lines.push('', '## Findings')
    for (const f of state.findings) lines.push('', f.slice(0, 4000))
  }

  if (citations.length > 0) {
    lines.push('', '## Citations', '')
    for (const c of citations) {
      lines.push(`- ${c.verified ? '✅' : '⚠️'} [${c.title || 'source'}](${c.url}) — ${c.claim.slice(0, 200)}`)
    }
  }

  if (state.experiments.length > 0) {
    lines.push('', '## Experiments')
    for (const e of state.experiments) {
      lines.push('', `### ${e.name} — ${e.status}`)
      if (e.command !== '') lines.push('', '```bash', e.command, '```')
      const metrics = Object.entries(e.metrics)
      if (metrics.length > 0) {
        lines.push('', '| Metric | Value |', '|--------|-------|')
        for (const [k, v] of metrics) lines.push(`| ${k} | ${v} |`)
      }
      if (e.logExcerpt !== '') lines.push('', `<details><summary>logs</summary>`, '', '```', e.logExcerpt.slice(0, 2000), '```', '', '</details>')
    }
  }

  if (state.repairAttempts > 0) lines.push('', `## Repairs: ${state.repairAttempts} attempt(s)`)
  if (state.review !== undefined) {
    lines.push('', '## Review', '', `- approved: **${state.review.approved}**`, `- confidence: **${state.review.confidence.toFixed(2)}**`)
    for (const issue of state.review.issues) lines.push(`- issue: ${issue}`)
  }
  lines.push('', '## Limitations', '',
    '- Citation marks: ✅ URL appeared in retrieved evidence, ⚠️ asserted but not observed.',
    '- Milestone-1 note: pipeline state lives in this artifact; durable session events land in milestone 2.')
  return lines.join('\n')
}
