/**
 * ResearchOps guardrail for DeepSeek Harness — vertical-slice port of the
 * risk policy from researchops-agent (src/researchops/guardrails/).
 *
 * Mapping from the Python platform:
 *   guardrails/permissions.py  → classify() below (deterministic rules)
 *   guardrails/policy.py       → the allow / deny / ask decision here
 *   guardrails/gateway.py      → dsh's tools/pre-execute waterfall itself
 *
 * dsh already owns the hard parts the Python gateway hand-rolled: the
 * allowlist registry, JSON-schema argument validation, execution timeouts
 * (guard/timeout-policy), audit logging (session events), and the approval
 * seam (ctx.approval, fail-closed). This plugin adds what is genuinely ours:
 * content-level risk classification and a per-scope call budget.
 *
 * Decision vocabulary: low → allow (delegate); medium/high → 'ask' so dsh's
 * approval service routes it to a human answerer (web UI) or fails closed in
 * headless; budget exhausted → deny with reason.
 *
 * @module @researchops/dsh-guardrail
 */

import type { Context } from '@deepseek-ai/cordis'
import z from '@deepseek-ai/schemastery'
import type { PreToolDecision, ToolExecution } from '@deepseek-ai/dsh-tools'

/** Cordis plugin name used by loader diagnostics. */
export const name = 'researchops-guardrail'

export interface Config {
  /**
   * Headless pre-approval (maps `RESEARCHOPS_APPROVAL_AUTO`): when true the
   * policy allows medium/high-risk calls itself instead of returning 'ask'.
   * The audit trail still records every decision as a session event.
   */
  autoApprove: boolean
  /** Maximum tool calls per mounted scope (maps `RESEARCHOPS_MAX_TOOL_CALLS`). */
  maxToolCalls: number
}

export const Config: z<Config> = z.object({
  autoApprove: z.boolean().default(false),
  maxToolCalls: z.number().default(200),
})

/** Risk ranks, ordered so content inspection can only escalate. */
type Risk = 'low' | 'medium' | 'high'
const RANK: Record<Risk, number> = { low: 0, medium: 1, high: 2 }

/** Command prefixes that are always high risk (destructive / external writes). */
const HIGH_COMMAND_PREFIXES = [
  'rm ', 'rm\t', 'sudo ', 'mkfs', 'dd ', 'git push', 'chmod 777',
  'curl -x post', 'wget --post', 'ssh ', 'scp ',
]

/** Commands with moderate side effects. */
const MEDIUM_COMMAND_PREFIXES = [
  'pip install', 'npm install', 'git clone', 'git commit', 'make ',
  'python', 'bash ', 'sh ', 'node ',
]

/** Default risk per harness tool name (content inspection may escalate). */
const TOOL_DEFAULT_RISK: Record<string, Risk> = {
  // read-only research / inspection
  read: 'low', glob: 'low', grep: 'low', ls: 'low',
  'web-search': 'low', 'web-fetch': 'low',
  // writes & execution
  write: 'medium', edit: 'medium', bash: 'medium', exec: 'medium',
  'process-run': 'medium',
  // external side effects
  'github-create-pull-request': 'high',
  'git-push': 'high',
}

/**
 * Read-only tools exposed by the ResearchOps MCP servers (mounted as
 * mcp__research__*). Everything else from MCP keeps the 'medium' default —
 * the allowlist posture is deliberate.
 */
const RESEARCH_MCP_READ_TOOLS = /search_papers|fetch_paper|search_citations|get_metadata|fetch_url|memory_search$/

function defaultRisk(toolName: string): Risk {
  if (toolName.startsWith('mcp__') && RESEARCH_MCP_READ_TOOLS.test(toolName)) return 'low'
  return TOOL_DEFAULT_RISK[toolName] ?? 'medium'
}

/** Commands inside tool arguments that escalate the base risk. */
function commandRisk(command: string): Risk {
  const cmd = command.trim().toLowerCase()
  const segments = cmd.split(/&&|;/).map(s => s.trim())
  for (const seg of segments) {
    if (HIGH_COMMAND_PREFIXES.some(p => seg.startsWith(p))) return 'high'
  }
  for (const seg of segments) {
    if (MEDIUM_COMMAND_PREFIXES.some(p => seg.startsWith(p))) return 'medium'
  }
  // unknown commands still execute code: treat as medium (sandboxed)
  return 'medium'
}

/**
 * Deterministic risk classification — the direct port of
 * `researchops.guardrails.permissions.classify`.
 */
export function classify(toolName: string, args: Readonly<Record<string, unknown>>): Risk {
  const base = defaultRisk(toolName)
  const commandKeys = ['command', 'cmd', 'script'] as const
  let risk: Risk = base
  for (const key of commandKeys) {
    const value = args[key]
    if (typeof value === 'string') {
      const candidate = commandRisk(value)
      if (RANK[candidate] > RANK[risk]) risk = candidate
    }
  }
  return risk
}

/**
 * Register the policy listener on the pre-execute waterfall. Cooperative
 * listeners delegate with next(); the budget guard denies; risk classification
 * either delegates (low / pre-approved) or hands the decision to the approval
 * seam ('ask' — the web UI answers, headless fails closed).
 */
export function apply(ctx: Context, config: Config): void {
  let calls = 0

  ctx.on('tools/pre-execute', async (exec: ToolExecution, next: () => Promise<PreToolDecision>): Promise<PreToolDecision> => {
    const args = (exec.arguments ?? {}) as Record<string, unknown>
    const risk = classify(exec.name, args)

    if (calls >= config.maxToolCalls) {
      return {
        kind: 'deny',
        reason: `researchops: tool-call budget exhausted (${config.maxToolCalls})`,
        info: { name: 'ResearchOpsBudgetError', code: 'RESEARCHOPS_BUDGET_EXHAUSTED' },
      }
    }

    if (RANK[risk] >= RANK.medium && !config.autoApprove) {
      return {
        kind: 'ask',
        reason: `researchops policy: ${exec.name} classified ${risk}-risk and requires approval`,
      }
    }

    calls++
    return next()
  })
}
