/**
 * Pantheon roster — the ResearchOps stage agents as named council members.
 *
 * The Greek theme is deliberate (Hermes v0.21 "Pantheon" homage): each stage
 * agent owns a named identity with a deterministic avatar seed, so the room
 * surface (milestone P2) and the durable room log can attribute every message.
 *
 * @module @researchops/dsh-pantheon/roster
 */
export interface PantheonMember {
    /** Stable member id used in room events and @mentions. */
    readonly id: string;
    /** Display name (the god). */
    readonly name: string;
    /** Greek name for the roster surface. */
    readonly greek: string;
    /** What this member owns in the pipeline. */
    readonly role: string;
    /** Deterministic avatar seed (UI renders it identically every run). */
    readonly avatarSeed: string;
}
export declare const ROSTER: Readonly<Record<string, PantheonMember>>;
/** The orchestrator itself: the messenger between gods (and the operator). */
export declare const HERMES: PantheonMember;
/** Member id for a pipeline stage kind (routing table, single place). */
export declare function memberForStage(kind: string): PantheonMember;
/** Narrow an unknown member id to a roster member. */
export declare function memberById(id: string): PantheonMember | undefined;
//# sourceMappingURL=roster.d.ts.map