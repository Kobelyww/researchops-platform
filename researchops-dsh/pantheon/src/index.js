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
import { randomUUID } from 'node:crypto';
import { HERMES, ROSTER } from "./roster.js";
/** Stable Cordis plugin name. */
export const name = 'researchops-pantheon';
/** Core services required to own room sessions. */
export const inject = ['sessions'];
export { ROSTER, HERMES } from "./roster.js";
/** The Agora room service. */
export class PantheonService {
    sessions;
    rooms = new Map();
    constructor(sessions) {
        this.sessions = sessions;
    }
    /** Open (or re-adopt) a named room; returns the room session id. */
    openRoom(name) {
        const existing = this.rooms.get(name);
        if (existing)
            return existing.id;
        const session = this.sessions.create(brandRoomId(name));
        this.rooms.set(name, session);
        session.append('pantheon/message', {
            from: { id: HERMES.id, name: HERMES.name, avatarSeed: HERMES.avatarSeed },
            text: `The Agora is open. Members: ${Object.values(ROSTER).map(m => m.name).join(', ')}.`,
            kind: 'system',
        });
        return session.id;
    }
    /** Post one message into a room as a roster member. */
    post(roomName, memberId, text, kind = 'stage') {
        const session = this.rooms.get(roomName);
        if (session === undefined)
            throw new Error(`pantheon: room "${roomName}" is not open`);
        const member = ROSTER[memberId] ?? HERMES;
        session.append('pantheon/message', {
            from: { id: member.id, name: member.name, avatarSeed: member.avatarSeed },
            text: text.slice(0, 4000),
            kind,
        });
    }
    /** Read a room's message history (structural read over the durable log). */
    history(roomName) {
        const session = this.rooms.get(roomName);
        if (session === undefined)
            return [];
        const out = [];
        // Snapshot read; the deprecation applies to per-seq reads, the snapshot is
        // the sanctioned bulk path for tooling (headless summarize() does the same).
        const events = session.snapshotEvents();
        for (const event of events) {
            if (event.type === 'pantheon/message' && event.data !== undefined) {
                out.push({ from: event.data.from.name, text: event.data.text });
            }
        }
        return out;
    }
}
/** Rooms are sessions with a reserved id prefix. */
function brandRoomId(name) {
    const safe = name.replace(/[^a-zA-Z0-9-]/g, '-').slice(0, 32) || 'agora';
    return `${safe}-agora-${randomUUID().slice(0, 8)}`;
}
/** Mount the service. */
export function apply(ctx) {
    const sessions = ctx.get('sessions');
    if (sessions === undefined)
        return;
    ctx.provide('pantheon', new PantheonService(sessions));
}
//# sourceMappingURL=index.js.map