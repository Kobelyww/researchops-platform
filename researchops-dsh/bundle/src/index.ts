/**
 * ResearchOps bundle marker. The bundle's effect lives in cordis.patch.yml
 * (guardrail policy, ResearchOps persona, research MCP mount); this module
 * exists so the workspace build graph has a typed entry for the package.
 *
 * @module @researchops/dsh-bundle
 */

export const name = 'researchops-bundle'

/** Human-readable summary surfaced by plugin-management tooling. */
export const description =
  'ResearchOps vertical slice: risk-classified tool guardrail, ResearchOps persona, research MCP server mount.'
