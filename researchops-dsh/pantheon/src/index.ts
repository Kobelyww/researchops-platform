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
import { appendFileSync, mkdirSync, writeFileSync } from 'node:fs'
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
    this.renderRoomHtml(roomName)
  }

  /** Regenerate the self-contained Discord-style HTML chat file for a room. */
  renderRoomHtml(roomName: string): string {
    const history = this.history(roomName)
    const path = this.roomFile(roomName).replace(/\.jsonl$/, '.html')
    const hue = (seed: string): number => {
      let h = 0
      for (const c of seed) h = (h * 31 + c.charCodeAt(0)) % 360
      return h
    }
    const members = new Map<string, { name: string; avatarSeed: string }>()
    for (const e of this.roomEvents(roomName)) members.set(e.from.name, e.from)
    const avatar = (name: string, seed: string): string =>
      `<div class="avatar" style="background:hsl(${hue(seed)},55%,42%)">${name[0]}</div>`
    const messages = history.map((m) => {
      const meta = members.get(m.from) ?? { name: m.from, avatarSeed: m.from }
      return `<div class="msg"><div class="row">${avatar(meta.name, meta.avatarSeed)}<span class="name">${meta.name}</span></div><div class="text">${m.text.replace(/</g, '&lt;')}</div></div>`
    }).join('\n')
    const roster = [...members.values()].map((m) =>
      `<div class="member">${avatar(m.name, m.avatarSeed)}<span>${m.name}</span></div>`).join('')
    const html = `<!doctype html><html><head><meta charset="utf-8"><title>ResearchOps Agora — ${roomName}</title><style>
body{background:#0d1117;color:#e6edf3;font-family:ui-sans-serif,system-ui;margin:0;display:flex;height:100vh}
aside{width:220px;background:#010409;border-right:1px solid #21262d;padding:16px}
.member{display:flex;align-items:center;gap:8px;padding:6px;color:#9198a1}
main{flex:1;padding:24px;overflow-y:auto}
h1{font-size:16px;color:#58a6ff}
.msg{background:#161b22;border:1px solid #21262d;border-radius:12px;padding:12px 16px;margin:10px 0}
.row{display:flex;align-items:center;gap:10px;margin-bottom:6px}
.avatar{width:34px;height:34px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:700;color:#fff}
.name{font-weight:600}
.text{white-space:pre-wrap;font-size:14px;line-height:1.5}
</style></head><body><aside><h1>🏛 The Agora</h1>${roster}</aside><main><h1>${roomName}</h1>${messages}</main></body></html>`
    try {
      writeFileSync(path, html)
    } catch { /* render is auxiliary */ }
    return path
  }

  private roomEvents(roomName: string): Array<{ from: { name: string; avatarSeed: string }; text: string; kind: string }> {
    const session = this.rooms.get(roomName)
    if (session === undefined) return []
    const events = session.snapshotEvents() as unknown as Array<{ type: string; data?: PantheonMessage }>
    return events.filter(e => e.type === 'pantheon/message' && e.data !== undefined).map(e => e.data as PantheonMessage)
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
