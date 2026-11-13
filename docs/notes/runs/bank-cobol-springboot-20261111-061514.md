The first full run of the harness: scenario v1, 4 sprints, Living Memory on with each agent's own store. Living Memory main was at PR #28 (reviewed procedural learning, phase 1); none of the remediation work existed yet.

The memory plumbing worked: no Living Memory CLI errors, and hooks fired in every session. What memory held was the problem. In the memory-only quiz, most should-know misses were capture gaps: the fact never reached the agent's store. The 2026-11-11 review traced this to four causes:

- The protocol rule "skip what docs record" sent stakeholder decisions into tickets and ADRs, so even the agent who received a decision saved no note about it.
- Codebase maps carried most of the stored facts, and they went stale: the architect's map still said money was long cents after the architect wrote ADR-004 (BigDecimal).
- Notes kept interim beliefs: an open bug note kept a hypothesis, and one note recorded a wrong conclusion with no verified flag.
- Sonnet-low leads made 3 memory calls in 15 work sessions, against 65 in 47 for Haiku agents.

This run predates the repo-access quiz and the work probes, so its only quiz is memory-only. Those findings became the Living Memory remediation phases measured later by run v2 C seed 1.
