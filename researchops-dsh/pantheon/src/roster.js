/**
 * Pantheon roster — the ResearchOps stage agents as named council members.
 *
 * The Greek theme is deliberate (Hermes v0.21 "Pantheon" homage): each stage
 * agent owns a named identity with a deterministic avatar seed, so the room
 * surface (milestone P2) and the durable room log can attribute every message.
 *
 * @module @researchops/dsh-pantheon/roster
 */
export const ROSTER = {
    athena: {
        id: 'athena', name: 'Athena', greek: 'Ἀθηνᾶ',
        role: 'strategy & planning — decomposes goals into task graphs',
        avatarSeed: 'athena-owl-01',
    },
    apollo: {
        id: 'apollo', name: 'Apollo', greek: 'Ἀπόλλων',
        role: 'research & prophecy — gathers papers, web evidence, citations',
        avatarSeed: 'apollo-lyre-01',
    },
    hephaestus: {
        id: 'hephaestus', name: 'Hephaestus', greek: 'Ἥφαιστος',
        role: 'the forge — experiments, code, sandboxed execution',
        avatarSeed: 'hephaestus-anvil-01',
    },
    argus: {
        id: 'argus', name: 'Argus', greek: 'Ἄργος',
        role: 'the hundred-eyed review — verifies claims and gates publication',
        avatarSeed: 'argus-eyes-01',
    },
};
/** The orchestrator itself: the messenger between gods (and the operator). */
export const HERMES = {
    id: 'hermes', name: 'Hermes', greek: 'Ἑρμῆς',
    role: 'the messenger — runs the pipeline and carries messages in the Agora',
    avatarSeed: 'hermes-caduceus-01',
};
/** Member id for a pipeline stage kind (routing table, single place). */
export function memberForStage(kind) {
    switch (kind) {
        case 'planner': return ROSTER.athena;
        case 'research':
        case 'repository': return ROSTER.apollo;
        case 'experiment':
        case 'code': return ROSTER.hephaestus;
        case 'review': return ROSTER.argus;
        default: return HERMES;
    }
}
/** Narrow an unknown member id to a roster member. */
export function memberById(id) {
    return ROSTER[id];
}
//# sourceMappingURL=roster.js.map