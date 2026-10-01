/**
 * @researchops/dsh-orchestrator — the ResearchOps pipeline as a dsh plugin.
 *
 * Milestone-1 port of researchops-agent/src/researchops/graph/: the LangGraph
 * state machine becomes one driver that creates stage-scoped Agents through
 * the core registry, steps them to quiescence, and makes routing decisions
 * with the pure functions in ./pipeline.ts.
 *
 * Design mapping (Python → dsh):
 *   graph/nodes.py stage agents   → one Agent per stage, tool subset via
 *                                   agentCtx.tools.restrict({allow})
 *   graph/routing.py              → pipeline.ts pure functions (in-process)
 *   graph/state.py AgentState     → PipelineState (in-memory; durable session
 *                                   events are milestone 2)
 *   graph/report.py               → pipeline.ts buildReport
 *   agents' tool subsets          → restrict({allow}) over global tools
 *
 * The driver reuses the headless app's startup service (task/argv/stdin) and
 * mirrors its run contract: stream progress to stderr, print the report to
 * stdout, exit 0 on completion.
 *
 * @module @researchops/dsh-orchestrator
 */

import { randomUUID } from 'node:crypto'
import { writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import type { Context } from '@deepseek-ai/cordis'
import z from '@deepseek-ai/schemastery'
import { brandString } from '@deepseek-ai/dsh-brand'
import { installModelSelection } from '@deepseek-ai/dsh-agent'
import type { Agent, ModelSelectionRef } from '@deepseek-ai/dsh-agent'
import type {} from '@deepseek-ai/dsh-agent-default-model'
import type {} from '@deepseek-ai/dsh-cmdline'
import type {} from '@deepseek-ai/dsh-headless'
import { createUserMessage } from '@deepseek-ai/dsh-llm'
import { defineTool } from '@deepseek-ai/dsh-tools'
import type { Session, SessionId } from '@deepseek-ai/dsh-session'
import { SessionSeq } from '@deepseek-ai/dsh-session'
import type {} from '@deepseek-ai/dsh-tools'
import * as pipeline from './pipeline.ts'

/** Stable Cordis plugin name. */
export const name = 'researchops-runner'

/** Core services required before the pipeline can start. */
export const inject = ['headlessStartup', 'agentDefaultModel', 'agents', 'sessions']

/** Plugin config. */
export interface Config {
  /** Maximum diagnose→repair rounds after a failed evaluation. */
  maxRepairAttempts: number
  /**
   * Publication sign-off mode: 'approval' (default) requires the operator to
   * answer the researchops_publish_report ask; 'auto' is the headless-CI
   * mode that publishes once the review approves (documented deviation).
   */
  signOff: 'approval' | 'auto'
}

export const Config: z<Config> = z.object({
  maxRepairAttempts: z.number().default(2),
  signOff: z.union(['approval', 'auto'] as const).default('approval'),
})

/** Per-stage tool subsets (global tool names; empty allow = toolless stage). */
const STAGE_TOOLS: Record<string, readonly string[]> = {
  planner: [],
  research: [
    'mcp__research__search_papers',
    'mcp__research__fetch_paper',
    'mcp__research__search_citations',
    'mcp__research__get_metadata',
    'mcp__research__fetch_url',
  ],
  experiment: ['bash', 'read', 'write', 'edit', 'glob', 'grep'],
  review: [],
}

/** One executed stage: its agent plus the assistant's final text. */
interface StageRun {
  agent: Agent
  output: string
}

/** Read the joined text of the last assistant message in a session log. */
function lastAssistantText(session: Session): string {
  let text = ''
  const length = session.seq
  for (let seq = 0; seq < length; seq++) {
    // Structural read of durable session events, mirroring the headless
    // runner's summarize() (module augmentation migration deferred there too).
    // Structural read; module augmentation migration is deferred upstream too.
    const event = session.eventAt(SessionSeq(seq)) as unknown as {
      type: string
      data?: { message?: { content?: Array<{ type: string; text?: string }> } }
    }
    if (event?.type !== 'assistant/message') continue
    const joined = (event.data?.message?.content ?? [])
      .filter(block => block.type === 'text')
      .map(block => block.text ?? '')
      .join('')
    if (joined !== '') text = joined
  }
  return text
}

/** Collect every durable tool-result text in a session log (grounding evidence). */
function toolResultText(session: Session): string {
  let text = ''
  const length = session.seq
  for (let seq = 0; seq < length; seq++) {
    const event = session.eventAt(SessionSeq(seq)) as unknown as { type: string; data?: unknown }
    if (event?.type !== 'tool/result') continue
    text += JSON.stringify(event.data) + '\n'
  }
  return text
}

/** Progress line to stderr (headless-style diagnostics channel). */
function progress(stderr: { write(chunk: string): unknown }, message: string): void {
  stderr.write(`dsh: researchops: ${message}\n`)
}

/** Create one stage agent with its scoped tool subset and run one prompt. */
async function runStage(
  agents: NonNullable<Context['agents']>,
  selection: { provider: string; model: string },
  cwd: string,
  stage: { kind: keyof typeof STAGE_TOOLS; persona: string; prompt: string },
  stderr: { write(chunk: string): unknown },
  setupOverride?: (agentCtx: Context) => void,
): Promise<StageRun> {
  const allow = STAGE_TOOLS[stage.kind] ?? []
  const setup = setupOverride ?? ((agentCtx: Context): void => {
    const selected: ModelSelectionRef = { current: selection, assembled: undefined }
    installModelSelection(agentCtx, selected)
    // Scope the global tools down to this stage's subset; an empty allow list
    // yields a toolless stage (planner/reviewer read and write no tools).
    agentCtx.tools?.restrict({ allow })
  })
  const { agent } = await agents.create({
    sessionId: brandString<SessionId>(`session-${randomUUID()}`),
    meta: { cwd },
    agentOptions: { provider: selection.provider, model: selection.model },
    setup,
  })
  progress(stderr, `stage ${stage.kind}: started (${allow.length === 0 ? 'toolless' : `${allow.length} tools`})`)
  agent.followup(createUserMessage({
    content: [{ type: 'text', text: stage.prompt }],
    source: { kind: 'user' },
  }))
  await agent.whenIdle()
  const output = lastAssistantText(agent.session)
  progress(stderr, `stage ${stage.kind}: done (${output.length} chars)`)
  return { agent, output }
}

/**
 * Run the ResearchOps pipeline for one task and request process exit.
 * @param ctx - plugin context carrying the Agent, default model, and launcher services.
 * @param config - repair budget.
 * @param task - the pipeline goal text (from the headless startup service).
 * @param io - process-facing effects.
 */
async function run(
  ctx: Context,
  config: Config,
  task: string,
  io: { stdout: { write(chunk: string): unknown }; stderr: { write(chunk: string): unknown }; exit(code: number): void },
): Promise<void> {
  await ctx.get('loader')?.await()
  const agents = ctx.get('agents')
  const defaultModel = ctx.get('agentDefaultModel')
  const sessions = ctx.get('sessions')
  if (agents === undefined || defaultModel === undefined || sessions === undefined) return

  const selection = defaultModel.currentSelection()
  const cwd = process.cwd()

  const state: pipeline.PipelineState = {
    goal: task,
    plan: [],
    findings: [],
    citations: [],
    experiments: [],
    repairAttempts: 0,
    review: undefined,
  }
  const stageAgents: Agent[] = []
  const stage = async (kind: keyof typeof STAGE_TOOLS, persona: string, prompt: string): Promise<StageRun> => {
    const run = await runStage(agents, selection, cwd, { kind, persona, prompt }, io.stderr)
    stageAgents.push(run.agent)
    return run
  }
  let evidence = ''

  // ---- plan ---------------------------------------------------------------
  progress(io.stderr, 'planning')
  const planner = await stage('planner' as const, 'planner',
    `[ResearchOps STAGE:planner]\nGoal: ${task}\n\n` +
    'Decompose the goal into a task graph. Respond with ONLY a JSON object: ' +
    '{"tasks": [{"id": "t1", "kind": "research|repository|code|experiment", "title": str, "description": str, "depends_on": [ids]}]}. ' +
    'Prefer 2-4 tasks. The last task should be an experiment that verifies the goal empirically.')
  state.plan = pipeline.parsePlan(planner.output).tasks
  progress(io.stderr, `plan: ${state.plan.map(t => `${t.id}:${t.kind}`).join(', ')}`)

  // ---- stage loop (port of graph routing) ---------------------------------
  let guard = 0
  for (;;) {
    const next = pipeline.nextReadyTask(state)
    if (next === undefined) break
    if (++guard > 16) { progress(io.stderr, 'stage guard tripped; continuing to evaluation'); break }
    next.status = 'running'

    if (next.kind === 'research' || next.kind === 'repository' || next.kind === 'code') {
      const run = await stage(next.kind === 'research' ? 'research' : 'experiment',
        next.kind,
        `[ResearchOps STAGE:${next.kind === 'research' ? 'research' : 'code'}]\n` +
        `Task: ${next.title}\nDescription: ${next.description}\nGoal: ${task}\n\n` +
        (next.kind === 'research'
          ? 'Use the research tools to gather real evidence. End with a fenced JSON block: {"summary": str, "citations": [{"claim": str, "title": str, "url": str}]}. Cite only URLs you actually retrieved.'
          : 'Implement or inspect what the task asks inside the workspace, then summarize what you did.'))
      state.findings.push(run.output)
      evidence += toolResultText(run.agent.session) + '\n'
      state.citations.push(...pipeline.parseCitations(run.output))
      next.status = 'done'
      continue
    }

    // experiment tasks enter through synthesis (port of nodes.synthesize)
    const findings = state.findings.join('\n\n').slice(0, 3000)
    const run = await stage('experiment', 'experimenter',
      `[ResearchOps STAGE:experiment]\nTask: ${next.title}\nDescription: ${next.description}\nGoal: ${task}\n\n` +
      `Research findings so far:\n${findings}\n\n` +
      'Create any needed files, run the experiment with the bash tool, and parse real numbers from output. ' +
      'End with a fenced JSON block: {"experiment": str, "command": str, "status": "success|failed", "metrics": {"name": number}, "log_excerpt": str}. ' +
      'Never invent metrics — parse them from real command output.')
    state.experiments.push(pipeline.parseExperiment(run.output))
    evidence += toolResultText(run.agent.session) + '\n'
    next.status = pipeline.evaluateSuccess(state) ? 'done' : 'failed'
    if (next.status === 'failed') break // fall through to diagnose
  }

  // ---- evaluate (deterministic + reviewer) --------------------------------
  const success = pipeline.evaluateSuccess(state)
  progress(io.stderr, `evaluation: success=${success} repairs=${state.repairAttempts}/${config.maxRepairAttempts}`)

  if (!success && state.repairAttempts < config.maxRepairAttempts) {
    state.repairAttempts++
    const failed = state.experiments.filter(e => e.status === 'failed').at(-1)
    const run = await stage('experiment', 'coder',
      `[ResearchOps STAGE:repair]\nGoal: ${task}\n` +
      `Last failure: ${JSON.stringify(failed ?? {}).slice(0, 800)}\n\n` +
      'Diagnose the failure from the workspace state, fix whatever is broken, then re-run the experiment. ' +
      'End with a fenced JSON block: {"experiment": str, "command": str, "status": "success|failed", "metrics": {"name": number}, "log_excerpt": str}.')
    state.experiments.push(pipeline.parseExperiment(run.output))
    evidence += toolResultText(run.agent.session) + '\n'
  }

  // ---- review --------------------------------------------------------------
  // The review stage owns the publication gate: the model calls
  // researchops_publish_report after its verdict; the call classifies
  // MEDIUM in the guardrail, so the ask routes through ctx.approval — a human
  // answerer in web/desktop, fail-closed 'unavailable' in headless. The
  // pipeline publishes only when the call was approved and succeeded.
  let publishApproved = false
  let publishAttempted = false
  const reviewSetup = (agentCtx: Context): void => {
    const selected: ModelSelectionRef = { current: selection, assembled: undefined }
    installModelSelection(agentCtx, selected)
    agentCtx.tools?.restrict({ allow: [] })
    if (config.signOff === 'auto') return // CI mode: publication pre-approved
    agentCtx.tools?.register(defineTool({
      name: 'researchops_publish_report',
      description: 'Request human approval to publish the final ResearchOps report. Call this once after your verdict JSON.',
      parameters: {
        summary: { type: 'string', required: true, description: 'One-sentence summary of the report being published.' },
      },
      output: {
        schema: {
          type: 'object',
          additionalProperties: false,
          properties: { published: { type: 'boolean', required: true } },
        },
        render: (_args: unknown, value: unknown) => {
          const v = (value ?? {}) as { published?: boolean; summary?: string }
          return [{ type: 'text', text: `publication ${v.published ? 'approved' : 'not approved'}: ${v.summary ?? ''}` }]
        },
      },
      execute: async (args: { summary: string }): Promise<{ published: boolean; summary: string }> => {
        publishAttempted = true
        publishApproved = true
        return { published: true, summary: String(args.summary ?? '') }
      },
    }))
  }
  const deterministic: pipeline.Review = {
    approved: success,
    confidence: state.citations.length === 0 ? (success ? 0.6 : 0.2)
      : pipeline.groundCitations(state, evidence).filter(c => c.verified).length / state.citations.length,
    issues: success ? [] : ['evaluation did not produce a successful experiment with metrics'],
  }
  const reviewPrompt =
    `[ResearchOps STAGE:review]\nGoal: ${task}\n\nFindings:\n${state.findings.join('\n\n').slice(0, 4000)}\n\n` +
    `Experiments: ${JSON.stringify(state.experiments.map(e => ({ name: e.name, status: e.status, metrics: e.metrics })))}\n\n` +
    'End with a fenced JSON block: {"approved": bool, "confidence": 0.0-1.0, "issues": [str]}. Be strict. ' +
    'Then call the researchops_publish_report tool with a one-sentence summary to request publication approval; ' +
    'if the call is denied, state in your final answer that the report was not approved for publication.'
  const reviewRun = await runStage(agents, selection, cwd,
    { kind: 'review', persona: 'reviewer', prompt: reviewPrompt }, io.stderr, reviewSetup)
  stageAgents.push(reviewRun.agent)
  state.review = pipeline.parseReview(reviewRun.output, deterministic)
  // approval flow evidence: a denied ask surfaces as an error tool result
  const reviewEvents = toolResultText(reviewRun.agent.session)
  progress(io.stderr, `review evidence: ${reviewEvents.length} chars, publish-name=${reviewEvents.includes('researchops_publish_report')}, approval-denied=${reviewEvents.includes('requires approval')}`)
  if (!publishAttempted && (reviewEvents.includes('researchops_publish_report') || reviewEvents.includes('requires approval'))) {
    publishAttempted = true // the call was made but denied before execution
  }
  if (config.signOff === 'auto') {
    publishAttempted = true
    publishApproved = state.review !== undefined && state.review.approved
  }

  // ---- report --------------------------------------------------------------
  const report = pipeline.buildReport(state, evidence)
  const reportPath = join(cwd, 'report.md')
  try {
    await writeFile(reportPath, report)
    progress(io.stderr, `report written to ${reportPath}`)
  } catch {
    progress(io.stderr, `could not write ${reportPath} (report still printed below)`)
  }
  for (const agent of stageAgents) {
    await sessions.flush(agent.session).catch(() => undefined)
  }
  io.stdout.write(report + '\n')
  // durable pipeline-state artifact (milestone 2): the state that a
  // projection can also rebuild from the stage sessions' events
  const pipelineStatePath = join(cwd, 'pipeline-state.json')
  try {
    await writeFile(pipelineStatePath, JSON.stringify({
      goal: state.goal,
      plan: state.plan,
      citations: pipeline.groundCitations(state, evidence),
      experiments: state.experiments,
      repairAttempts: state.repairAttempts,
      review: state.review,
      publish: { attempted: publishAttempted, approved: publishApproved },
      success,
      finishedAt: new Date().toISOString(),
    }, null, 2))
    progress(io.stderr, `pipeline state written to ${pipelineStatePath}`)
  } catch {
    progress(io.stderr, `could not write ${pipelineStatePath}`)
  }
  const completed = success && state.review !== undefined && state.review.approved && publishApproved
  io.exit(completed ? 0 : 1)
}

/**
 * Mount the runner. It waits for the headless startup service (task/stdin/argv)
 * the same way the one-shot runner does, so `dsh --profile researchops "goal"`
 * drives the pipeline.
 */
export function apply(ctx: Context, config: Config): void {
  const startup = ctx.get('headlessStartup')
  if (startup === undefined) return
  // Read through the global service store, not the property proxy: appExit is
  // an optional host value, never an injected dependency (mirrors headless).
  const exit = ctx.get('appExit')
  if (exit === undefined) {
    throw new Error('researchops-runner: the launcher must provide ctx.appExit before the tree mounts')
  }
  const io = { stdout: process.stdout, stderr: process.stderr, exit }
  void (async () => {
    try {
      const task = startup.task ?? ''
      if (task.trim() === '') throw new Error('a task is required')
      await run(ctx, config, task, io)
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : String(error)
      io.stderr.write(`dsh: researchops: ${message}\n`)
      io.exit(1)
    }
  })()
}
