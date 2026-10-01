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
import type { Context } from '@deepseek-ai/cordis';
import type { SessionId } from '@deepseek-ai/dsh-session';
/** Stable Cordis plugin name. */
export declare const name = "researchops-pantheon";
/** Core services required to own room sessions. */
export declare const inject: string[];
export { ROSTER, HERMES } from './roster.ts';
export type { PantheonMember } from './roster.ts';
/** One message in the Agora (durable `pantheon/message` event payload). */
export interface PantheonMessage {
    from: {
        id: string;
        name: string;
        avatarSeed: string;
    };
    text: string;
    kind: 'stage' | 'operator' | 'system';
}
declare module '@deepseek-ai/dsh-session' {
    interface SessionEventMap {
        'pantheon/message': PantheonMessage;
    }
}
declare module '@deepseek-ai/cordis' {
    interface Context {
        pantheon: PantheonService;
    }
}
/** The Agora room service. */
export declare class PantheonService {
    private readonly sessions;
    private readonly rooms;
    constructor(sessions: NonNullable<Context['sessions']>);
    /** Open (or re-adopt) a named room; returns the room session id. */
    openRoom(name: string): SessionId;
    /** Post one message into a room as a roster member. */
    post(roomName: string, memberId: string, text: string, kind?: PantheonMessage['kind']): void;
    /** Read a room's message history (structural read over the durable log). */
    history(roomName: string): Array<{
        from: string;
        text: string;
    }>;
}
/** Mount the service. */
export declare function apply(ctx: Context): void;
//# sourceMappingURL=index.d.ts.map