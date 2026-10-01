/**
 * @researchops/dsh-pantheon — the Agora: a durable group room where the
 * ResearchOps gods post as themselves and the operator can follow the council.
 *
 * Design (P1, core-data-plane only):
 * - The room IS a session (`ctx.sessions.create`), so every message is a
 *   durable `pantheon/message` event — persistent, replayable, inspectable
 *   from the session JSONL, and later renderable by a chat surface (P2).
 * - `post()` appends with the member identity; attribution lives in the event
 *   data (name + avatarSeed), never in the session header.
 * - The orchestrator posts stage outcomes as the stage's god; milestone P2
 *   adds @mention routing into stage-agent followups and the chat UI.
 *
 * @module @researchops/dsh-pantheon
 */

import { randomUUID } from 'node:crypto'
import { appendFileSync, mkdirSync } from 'node:fs'
import { join } from 'node:path'
import type { Context } from '@deepseek-ai/cordis'
import type { Session, SessionId } from '@deepseek-ai/dsh-session'
import { HERMES, ROSTER, type PantheonMember } from './roster.ts'

/** Stable Cordis plugin name. */
export const name = 'researchops-pantheon'

/** Core services required to own room sessions. */
export const inject = ['sessions']

export { ROSTER, HERMES, memberForStage, memberById } from './roster.ts'
export type { PantheonMember } from './roster.ts'

/** One message in the Agora (durable `pantheon/message` event payload). */
export interface PantheonMessage {
  from: { id: string; name: string; avatarSeed: string }
  text: string
  kind: 'stage' | 'operator' | 'system'
}

declare module '@deepseek-ai/dsh-session' {
  interface SessionEventMap {
    'pantheon/message': PantheonMessage
  }
}

declare module '@deepseek-ai/cordis' {
  interface Context {
    pantheon: PantheonService
  }
}

/** The Agora room service. */
export class PantheonService {
  private readonly rooms = new Map<string, Session>()

  constructor(
    private readonly sessions: NonNullable<Context['sessions']>,
    private readonly cwd: string,
  ) {}

  /**
   * P1 durability: an append-only room log next to the session store.
   * The session-event path is authoritative in-memory; adopting the
   * persistence write-handle lifecycle for bare sessions is P2 work.
   */
  private roomFile(roomName: string): string {
    const dir = join(this.cwd, 'pantheon')
    mkdirSync(dir, { recursive: true })
    return join(dir, `${roomName}.jsonl`)
  }

  private writeRoomLine(roomName: string, line: object): void {
    try {
      appendFileSync(this.roomFile(roomName), JSON.stringify(line) + '\n')
    } catch {
      // the room log is auxiliary in P1; never fail a stage over it
    }
  }

  /** Open (or re-adopt) a named room; returns the room session id. */
  openRoom(name: string): SessionId {
    const existing = this.rooms.get(name)
    if (existing) return existing.id
    // meta.cwd is mandatory: storage backends key session directories off it.
    const session = this.sessions.create(brandRoomId(name), { meta: { cwd: this.cwd } })
    this.rooms.set(name, session)
    const opener: PantheonMessage = {
      from: { id: HERMES.id, name: HERMES.name, avatarSeed: HERMES.avatarSeed },
      text: `The Agora is open. Members: ${Object.values(ROSTER).map(m => m.name).join(', ')}.`,
      kind: 'system',
    }
    session.append('pantheon/message', opener)
    this.writeRoomLine(session.id, opener)
    return session.id
  }

  /** Post one message into a room as a roster member. */
  post(roomName: string, memberId: string, text: string, kind: PantheonMessage['kind'] = 'stage'): void {
    const session = this.rooms.get(roomName)
    if (session === undefined) throw new Error(`pantheon: room "${roomName}" is not open`)
    const member: PantheonMember = ROSTER[memberId] ?? HERMES
    const message: PantheonMessage = {
      from: { id: member.id, name: member.name, avatarSeed: member.avatarSeed },
      text: text.slice(0, 4000),
      kind,
    }
    session.append('pantheon/message', message)
    this.writeRoomLine(session.id, message)
  }

  /** The room's session (callers flush it like any session). */
  sessionOf(roomName: string): Session | undefined {
    return this.rooms.get(roomName)
  }

  /** Read a room's message history (structural read over the durable log). */
  history(roomName: string): Array<{ from: string; text: string }> {
    const session = this.rooms.get(roomName)
    if (session === undefined) return []
    const out: Array<{ from: string; text: string }> = []
    // Snapshot read; the deprecation applies to per-seq reads, the snapshot is
    // the sanctioned bulk path for tooling (headless summarize() does the same).
    const events = session.snapshotEvents() as unknown as Array<{ type: string; data?: PantheonMessage }>
    for (const event of events) {
      if (event.type === 'pantheon/message' && event.data !== undefined) {
        out.push({ from: event.data.from.name, text: event.data.text })
      }
    }
    return out
  }
}

/** Rooms are sessions with a reserved id prefix. */
function brandRoomId(name: string): SessionId {
  const safe = name.replace(/[^a-zA-Z0-9-]/g, '-').slice(0, 32) || 'agora'
  return `${safe}-agora-${randomUUID().slice(0, 8)}` as unknown as SessionId
}

/** Mount the service. */
export function apply(ctx: Context): void {
  const sessions = ctx.get('sessions')
  if (sessions === undefined) return
  const fs = ctx.get('fs')
  const cwd = fs === undefined ? process.cwd() : fs.processPath(fs.resolve('.'))
  ctx.provide('pantheon', new PantheonService(sessions, cwd))
}
